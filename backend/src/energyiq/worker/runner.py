"""Claim, lease, run, and finish extraction runs (spec 0012/0002 AC-3).

The database is the queue. A claim is one transaction: ``SELECT ... FOR UPDATE
SKIP LOCKED`` on a queued run, or on a running run whose lease has expired,
then an update that records the owner, the new lease, and ``attempts + 1``. A
crash therefore leaves a ``running`` row that the next claim recovers once the
lease lapses, until ``run_max_attempts`` is spent. Finishing is a compare and
set on the lease owner, so a worker that lost its lease cannot overwrite the
worker that took over. This process never confirms an invoice.
"""

import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from energyiq.documents.models import ExtractionRunRow, SourceDocumentRow
from energyiq.documents.pdf_text import NORMALIZATION_VERSION, has_native_text
from energyiq.documents.storage import DocumentStore
from energyiq.platform.clock import get_now
from energyiq.platform.logging import ERROR_LOGGER
from energyiq.platform.settings import Settings
from energyiq.worker.sandbox import ChildLimits, ChildResult, run_pdf_child

POLL_SECONDS = 2.0
_log = logging.getLogger(ERROR_LOGGER)

Parser = Callable[[bytes, ChildLimits], ChildResult]


@dataclass(frozen=True)
class Claim:
    run_id: UUID
    storage_key: UUID


def child_limits(settings: Settings) -> ChildLimits:
    return ChildLimits(
        max_pages=settings.pdf_max_pages,
        max_text_bytes=settings.pdf_max_text_bytes,
        cpu_seconds=settings.pdf_cpu_seconds,
        wall_seconds=settings.pdf_wall_seconds,
        memory_bytes=settings.pdf_memory_bytes,
    )


def check_isolation(settings: Settings) -> None:
    """Refuse an unisolated worker outside development and test."""
    if settings.worker_isolation == "none" and settings.env not in ("dev", "test"):
        raise RuntimeError(
            "ENERGYIQ_WORKER_ISOLATION=none is only allowed when ENERGYIQ_ENV"
            " is dev or test"
        )


def new_owner() -> str:
    return f"{socket.gethostname()}-{os.getpid()}-{uuid4().hex[:8]}"


class Worker:
    def __init__(
        self,
        settings: Settings,
        factory: sessionmaker[Session],
        store: DocumentStore,
        *,
        owner: str | None = None,
        now: Callable[[], datetime] = get_now,
        parser: Parser = run_pdf_child,
    ) -> None:
        self.settings = settings
        self.factory = factory
        self.store = store
        self.owner = owner or new_owner()
        self.now = now
        self.parser = parser

    # claiming -------------------------------------------------------------

    def claim(self) -> Claim | None:
        """Take one runnable run, failing any whose attempts are spent."""
        while True:
            with self.factory() as session, session.begin():
                now = self.now()
                run = session.scalars(
                    select(ExtractionRunRow)
                    .where(
                        or_(
                            ExtractionRunRow.state == "queued",
                            (ExtractionRunRow.state == "running")
                            & (ExtractionRunRow.lease_expires_at <= now),
                        )
                    )
                    .order_by(ExtractionRunRow.created_at, ExtractionRunRow.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                ).one_or_none()
                if run is None:
                    return None
                document = session.get(SourceDocumentRow, run.document_id)
                assert document is not None
                if document.deleted_at is not None:
                    self._fail(run, "document_deleted", now)
                    continue
                if run.attempts >= self.settings.run_max_attempts:
                    self._fail(run, "attempts_exhausted", now)
                    continue
                run.state = "running"
                run.attempts += 1
                run.lease_owner = self.owner
                run.lease_expires_at = now + timedelta(
                    seconds=self.settings.run_lease_seconds
                )
                run.started_at = now
                run.error_code = None
                return Claim(run.id, document.storage_key)

    @staticmethod
    def _fail(run: ExtractionRunRow, code: str, now: datetime) -> None:
        run.state = "failed"
        run.error_code = code
        run.finished_at = now
        run.lease_owner = None
        run.lease_expires_at = None

    # running --------------------------------------------------------------

    def process(self, claim: Claim) -> bool:
        """Parse the stored file and record the outcome; ``False`` if the lease was lost."""
        try:
            data = self.store.read(claim.storage_key)
        except FileNotFoundError:
            return self._finish(claim, ChildResult(False, "source_missing"))
        result = self.parser(data, child_limits(self.settings))
        return self._finish(claim, result)

    def _finish(self, claim: Claim, result: ChildResult) -> bool:
        with self.factory() as session, session.begin():
            values: dict[str, object] = {
                "finished_at": self.now(),
                "lease_owner": None,
                "lease_expires_at": None,
            }
            if result.ok:
                values.update(
                    state="succeeded",
                    error_code=None,
                    output={
                        "page_count": result.page_count,
                        "normalization": NORMALIZATION_VERSION,
                        "native_text": has_native_text(result.pages),
                        "pages": [page.to_json() for page in result.pages],
                    },
                )
            else:
                values.update(state="failed", error_code=result.code, output=None)
            done = cast(
                "CursorResult[tuple[()]]",
                session.execute(
                    update(ExtractionRunRow)
                    .where(
                        ExtractionRunRow.id == claim.run_id,
                        ExtractionRunRow.state == "running",
                        ExtractionRunRow.lease_owner == self.owner,
                        ExtractionRunRow.lease_expires_at > self.now(),
                    )
                    .values(**values)
                    .execution_options(synchronize_session=False)
                ),
            )
            finished = done.rowcount == 1
            if finished:
                self._drop_output_if_deleted(session, claim.run_id)
        if not finished:
            _log.warning("run %s: lease lost before finish", claim.run_id)
        return finished

    @staticmethod
    def _drop_output_if_deleted(session: Session, run_id: UUID) -> None:
        """Derived data of a tombstoned document never survives a finish."""
        session.execute(
            update(ExtractionRunRow)
            .where(
                ExtractionRunRow.id == run_id,
                ExtractionRunRow.document_id.in_(
                    select(SourceDocumentRow.id).where(
                        SourceDocumentRow.deleted_at.is_not(None)
                    )
                ),
            )
            .values(output=None)
            .execution_options(synchronize_session=False)
        )

    def run_once(self) -> bool:
        """Claim and process one run; ``False`` when nothing was runnable."""
        claim = self.claim()
        if claim is None:
            return False
        self.process(claim)
        return True

    # serving --------------------------------------------------------------

    def serve(self, stop: threading.Event) -> None:
        """Poll until ``stop`` is set, with ``worker_concurrency`` threads."""

        def loop() -> None:
            while not stop.is_set():
                try:
                    busy = self.run_once()
                except Exception:  # noqa: BLE001 - a bad run must not kill the loop
                    _log.exception("worker iteration failed")
                    busy = False
                if not busy:
                    stop.wait(POLL_SECONDS)

        threads = [
            threading.Thread(target=loop, name=f"worker-{n}", daemon=True)
            for n in range(self.settings.worker_concurrency)
        ]
        for thread in threads:
            thread.start()
        while not stop.is_set():
            time.sleep(0.2)
        for thread in threads:
            thread.join(timeout=self.settings.pdf_wall_seconds + 5)

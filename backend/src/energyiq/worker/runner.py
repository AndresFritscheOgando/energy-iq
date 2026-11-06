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
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import CursorResult, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from energyiq.documents.models import ExtractionRunRow, SourceDocumentRow
from energyiq.documents.pdf_text import NORMALIZATION_VERSION, has_native_text
from energyiq.documents.storage import DocumentStore
from energyiq.extraction.ollama import BAD_REQUEST, OllamaProvider
from energyiq.extraction.provider import (
    CANCELLED,
    MODEL_MISSING,
    PROVIDER_TIMEOUT,
    PROVIDER_UNAVAILABLE,
    ExtractionLimits,
    ExtractionOutcome,
    Provider,
    run_extraction,
)
from energyiq.platform.clock import get_now
from energyiq.platform.logging import ERROR_LOGGER
from energyiq.platform.settings import LEASE_MARGIN_SECONDS, Settings
from energyiq.worker.sandbox import ChildLimits, ChildResult, run_pdf_child

POLL_SECONDS = 2.0
_log = logging.getLogger(ERROR_LOGGER)

Parser = Callable[[bytes, ChildLimits], ChildResult]

# A model outage fails the run (the owner can retry or enter the invoice by
# hand). Any other extraction failure means the model answered badly: the page
# text is still good, so the run succeeds and the document stays in review.
OUTAGE_CODES = frozenset(
    {PROVIDER_TIMEOUT, PROVIDER_UNAVAILABLE, MODEL_MISSING, BAD_REQUEST}
)


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
    if settings.worker_isolation == "container" and not sys.platform.startswith(
        "linux"
    ):
        raise RuntimeError(
            "ENERGYIQ_WORKER_ISOLATION=container needs a Linux host or container;"
            " use none in dev or test"
        )
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
        provider: Provider | None = None,
    ) -> None:
        self.settings = settings
        self.factory = factory
        self.store = store
        self.owner = owner or new_owner()
        self.now = now
        self.parser = parser
        if provider is None and settings.extraction_enabled:
            assert settings.ollama_model is not None  # checked by Settings
            provider = OllamaProvider(
                settings.ollama_base_url,
                settings.ollama_model,
                settings.ollama_timeout_seconds,
            )
        self.provider = provider
        self._stopping = threading.Event()

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
        except OSError:
            # A permission or disk error is final for this run; leaving it
            # ``running`` would burn an attempt and end as attempts_exhausted.
            return self._finish(claim, ChildResult(False, "source_unreadable"))
        result = self.parser(data, child_limits(self.settings))
        outcome: ExtractionOutcome | None = None
        if result.ok and self.provider is not None and has_native_text(result.pages):
            if not self._renew(claim):
                return False
            outcome = run_extraction(
                self.provider,
                result.pages,
                ExtractionLimits(
                    max_pages=self.settings.pdf_max_pages,
                    max_text_bytes=self.settings.pdf_max_text_bytes,
                    max_output_bytes=self.settings.extraction_max_output_bytes,
                    max_attempts=self.settings.extraction_max_attempts,
                    # The lease was just renewed; stop starting attempts well
                    # before it can lapse under us.
                    deadline_seconds=max(
                        1.0, self.settings.run_lease_seconds - LEASE_MARGIN_SECONDS / 2
                    ),
                ),
                cancelled=self._stopping.is_set,
            )
        return self._finish(claim, result, outcome)

    def _renew(self, claim: Claim) -> bool:
        """Extend our own lease before the model call; ``False`` if it was lost."""
        with self.factory() as session, session.begin():
            now = self.now()
            done = cast(
                "CursorResult[tuple[()]]",
                session.execute(
                    update(ExtractionRunRow)
                    .where(
                        ExtractionRunRow.id == claim.run_id,
                        ExtractionRunRow.state == "running",
                        ExtractionRunRow.lease_owner == self.owner,
                        ExtractionRunRow.lease_expires_at > now,
                    )
                    .values(
                        lease_expires_at=now
                        + timedelta(seconds=self.settings.run_lease_seconds)
                    )
                    .execution_options(synchronize_session=False)
                ),
            )
            return done.rowcount == 1

    def _finish(
        self,
        claim: Claim,
        result: ChildResult,
        extraction: ExtractionOutcome | None = None,
    ) -> bool:
        with self.factory() as session, session.begin():
            values: dict[str, object] = {
                "finished_at": self.now(),
                "lease_owner": None,
                "lease_expires_at": None,
            }
            if result.ok:
                output: dict[str, object] = {
                    "page_count": result.page_count,
                    "normalization": NORMALIZATION_VERSION,
                    "native_text": has_native_text(result.pages),
                    "pages": [page.to_json() for page in result.pages],
                }
                state, code = "succeeded", None
                release = False
                if extraction is not None:
                    meta = asdict(extraction.metadata)
                    values.update(
                        model=extraction.metadata.model,
                        prompt_version=extraction.metadata.prompt_revision,
                    )
                    if extraction.metadata.error_code == CANCELLED:
                        # A shutdown, not a failure: give the run back to the
                        # queue and return the attempt it used.
                        release = True
                    elif extraction.proposal is not None:
                        output["extraction"] = {
                            "metadata": meta,
                            "proposal": extraction.proposal.to_json(),
                        }
                    elif extraction.metadata.error_code in OUTAGE_CODES:
                        # No pages kept: the run failed, the PDF is intact, and
                        # a retry parses it again.
                        state, code = "failed", extraction.metadata.error_code
                        output = {"extraction": {"metadata": meta}}
                    else:
                        output["extraction"] = {"metadata": meta}
                if release:
                    values.update(
                        state="queued",
                        error_code=None,
                        output=None,
                        started_at=None,
                        finished_at=None,
                        attempts=ExtractionRunRow.attempts - 1,
                    )
                else:
                    values.update(state=state, error_code=code, output=output)
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

    def _shutdown_wait(self) -> float:
        """Longest a thread may need to finish its run after a stop request."""
        wait = self.settings.pdf_wall_seconds + 5
        if self.provider is not None:
            wait += (
                self.settings.ollama_timeout_seconds
                * self.settings.extraction_max_attempts
            )
        return float(wait)

    # serving --------------------------------------------------------------

    def serve(self, stop: threading.Event) -> None:
        """Poll until ``stop`` is set, with ``worker_concurrency`` threads."""

        self._stopping = stop  # a shutdown cancels a run before its next model call

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
            thread.join(timeout=self._shutdown_wait())

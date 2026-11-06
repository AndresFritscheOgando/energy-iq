"""Run the worker: ``uv run python -m energyiq.worker`` (spec 0012/0002 AC-3).

Exits 2 on invalid settings or an unsupported isolation mode, naming the
problem and never a secret.
"""

import signal
import sys
import threading
from types import FrameType

from pydantic import ValidationError

from energyiq.documents.storage import LocalDocumentStore
from energyiq.platform.db import build_engine, session_factory
from energyiq.platform.logging import configure_logging
from energyiq.platform.settings import Settings
from energyiq.worker.runner import Worker, check_isolation

EXIT_CONFIG = 2


def main() -> int:
    try:
        settings = Settings()
        check_isolation(settings)
    except ValidationError as exc:
        fields = sorted({".".join(map(str, error["loc"])) for error in exc.errors()})
        print(f"invalid settings: {', '.join(fields)}", file=sys.stderr)
        return EXIT_CONFIG
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG
    configure_logging(settings.log_level)
    engine = build_engine(settings)
    stop = threading.Event()

    def request_stop(_signal: int, _frame: FrameType | None) -> None:
        stop.set()

    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, request_stop)
    worker = Worker(
        settings, session_factory(engine), LocalDocumentStore(settings.document_root)
    )
    try:
        worker.serve(stop)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

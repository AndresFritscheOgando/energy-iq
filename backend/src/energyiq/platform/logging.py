"""JSON log lines for the ``energyiq`` logger tree (spec 0008 AC-10)."""

import json
import logging
import sys
from datetime import UTC, datetime

from energyiq.platform.http.formats import format_utc

ACCESS_LOGGER = "energyiq.access"
ERROR_LOGGER = "energyiq.errors"
_ROOT = "energyiq"
_HANDLER_NAME = "energyiq-json"


class JsonFormatter(logging.Formatter):
    """One JSON object per line.

    Access records carry exactly ``timestamp``, ``level`` and the fields in
    their ``access`` extra. Other records carry the logger, message, the
    request id when given, and the traceback when there is one.
    """

    def format(self, record: logging.LogRecord) -> str:
        timestamp = format_utc(datetime.fromtimestamp(record.created, UTC))
        access: object = getattr(record, "access", None)
        if isinstance(access, dict):
            line: dict[str, object] = {
                "timestamp": timestamp,
                "level": record.levelname,
            }
            line.update(access)  # pyright: ignore[reportUnknownArgumentType]
            return json.dumps(line, separators=(",", ":"))

        line = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id: object = getattr(record, "request_id", None)
        if request_id is not None:
            line["request_id"] = request_id
        if record.exc_info:
            line["traceback"] = self.formatException(record.exc_info)
        return json.dumps(line, separators=(",", ":"))


def configure_logging(level: str) -> None:
    """Install the JSON handler once per process; later calls only set levels.

    The access logger stays at INFO so every request writes its line whatever
    the application level is.
    """
    root = logging.getLogger(_ROOT)
    if not any(handler.get_name() == _HANDLER_NAME for handler in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    logging.getLogger(ACCESS_LOGGER).setLevel(logging.INFO)

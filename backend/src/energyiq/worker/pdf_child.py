"""The PDF parse child (spec 0012/0002 "Parse isolation").

Run as ``python -I pdf_child.py MAX_PAGES MAX_TEXT_BYTES CPU_SECONDS MEMORY_BYTES``.
The PDF bytes arrive on stdin and one JSON object leaves on stdout. The file
imports only the standard library and ``pypdf``, never ``energyiq``: the child
has no database, no settings, no file path, and an empty environment. On Linux
it sets resource limits before it reads a single byte of the PDF.

Result: ``{"ok": true, "page_count": N}`` or ``{"ok": false, "code": "..."}``.
"""

import importlib
import io
import json
import sys
from typing import Any


def _limit(cpu_seconds: int, memory_bytes: int) -> None:
    try:
        resource: Any = importlib.import_module("resource")
    except ImportError:  # Windows: development mode only, no rlimits
        return
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds))
    resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _emit(result: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(result, separators=(",", ":")))
    sys.stdout.flush()


def probe(data: bytes, max_pages: int) -> dict[str, object]:
    """Structure checks only; text extraction arrives with spec 0003."""
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            return {"ok": False, "code": "pdf_encrypted"}
        page_count = len(reader.pages)
    except MemoryError:
        return {"ok": False, "code": "pdf_parse_resource"}
    except (PyPdfError, ValueError, KeyError, TypeError, OSError, RecursionError):
        return {"ok": False, "code": "pdf_malformed"}
    if page_count < 1:
        return {"ok": False, "code": "pdf_malformed"}
    if page_count > max_pages:
        return {"ok": False, "code": "pdf_too_many_pages"}
    return {"ok": True, "page_count": page_count}


def main(argv: list[str]) -> int:
    max_pages, _max_text_bytes, cpu_seconds, memory_bytes = (int(a) for a in argv[1:5])
    _limit(cpu_seconds, memory_bytes)
    data = sys.stdin.buffer.read()
    try:
        _emit(probe(data, max_pages))
    except MemoryError:
        _emit({"ok": False, "code": "pdf_parse_resource"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

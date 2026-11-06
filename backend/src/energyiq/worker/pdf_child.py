"""The PDF parse child (spec 0012/0002 "Parse isolation").

Run as ``python -I pdf_child.py MAX_PAGES MAX_TEXT_BYTES CPU_SECONDS MEMORY_BYTES``.
The PDF bytes arrive on stdin and one JSON object leaves on stdout. The file
imports only the standard library and ``pypdf``, never ``energyiq``: the child
has no database, no settings, no file path, and an empty environment. On Linux
it sets resource limits before it reads a single byte of the PDF.

Result: ``{"ok": true, "page_count": N, "pages": [...]}`` or
``{"ok": false, "code": "..."}``. Each page holds ``page_number``,
``normalized_text``, ``quality_code``, and ``text_digest`` (spec 0012/0003).
Page text is untrusted data: it is normalized and measured here, never
interpreted.
"""

import hashlib
import importlib
import io
import json
import re
import sys
import unicodedata
from typing import Any

NORMALIZATION_VERSION = "n1"
_SPACES = re.compile(r" {2,}")
_BLANK_RUNS = re.compile(r"\n{3,}")


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
    # Raw UTF-8 bytes: escaping accents would inflate text past the output cap.
    payload = json.dumps(result, separators=(",", ":"), ensure_ascii=False)
    sys.stdout.buffer.write(payload.encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()


def normalize(raw: str) -> str:
    """Deterministic text normalization, version ``n1``.

    NFKC folds ligatures and full width digits. Control and format characters
    (zero width, bidi overrides) are dropped, line breaks become a newline,
    runs of blanks collapse, and runs of blank lines shrink to one. Evidence
    offsets refer to this exact string.
    """
    text = unicodedata.normalize("NFKC", raw)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    kept: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if char == "\n":
            kept.append(char)
        elif char in "\t\f\v" or category == "Zs":
            kept.append(" ")
        elif category in ("Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"):
            continue
        else:
            kept.append(char)
    lines = [_SPACES.sub(" ", line).strip() for line in "".join(kept).split("\n")]
    return _BLANK_RUNS.sub("\n\n", "\n".join(lines)).strip()


def page_record(number: int, raw: str) -> dict[str, object]:
    text = normalize(raw)
    return {
        "page_number": number,
        "normalized_text": text,
        "quality_code": "has_text" if text else "empty",
        "text_digest": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def probe(
    data: bytes, max_pages: int, max_text_bytes: int = 256 * 1024
) -> dict[str, object]:
    """Structure checks, then page text one page at a time."""
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
    pages: list[dict[str, object]] = []
    total = 0
    for number in range(1, page_count + 1):
        try:
            raw = reader.pages[number - 1].extract_text()
        except MemoryError:
            return {"ok": False, "code": "pdf_parse_resource"}
        except (PyPdfError, ValueError, KeyError, TypeError, OSError, RecursionError):
            return {"ok": False, "code": "pdf_malformed"}
        record = page_record(number, raw)
        total += len(str(record["normalized_text"]).encode("utf-8"))
        if total > max_text_bytes:  # never truncate: a cut bill could hide a total
            return {"ok": False, "code": "pdf_text_too_large"}
        pages.append(record)
    return {"ok": True, "page_count": page_count, "pages": pages}


def main(argv: list[str]) -> int:
    max_pages, max_text_bytes, cpu_seconds, memory_bytes = (int(a) for a in argv[1:5])
    _limit(cpu_seconds, memory_bytes)
    data = sys.stdin.buffer.read()
    try:
        _emit(probe(data, max_pages, max_text_bytes))
    except MemoryError:
        _emit({"ok": False, "code": "pdf_parse_resource"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

"""Page text contract and evidence spans (spec 0012/0003 AC-1, AC-2).

The parse child returns page text. The worker parent never trusts it: this
module re-checks the shape, the page order, the digest, the quality code, the
size, and that the text holds no control or format characters. Page text is
data. Nothing here interprets it, so instruction text inside a PDF is just a
string with a span.

Evidence offsets are character offsets into ``normalized_text`` (normalization
``n1``, applied by the child). A span therefore always round trips: the quote
is exactly ``normalized_text[start:end]``. The raw PDF text is not kept; the
original PDF is the raw source.
"""

import hashlib
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast

SourceKind = Literal["native", "ocr", "vision"]
QualityCode = Literal["has_text", "empty"]

NORMALIZATION_VERSION = "n1"
MAX_SPANS_PER_PAGE = 500
_FORBIDDEN = {"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"}


@dataclass(frozen=True)
class Span:
    """A half open character range of one page's normalized text."""

    page_number: int
    start: int
    end: int


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    normalized_text: str
    source_kind: SourceKind
    quality_code: QualityCode
    text_digest: str

    def spans(self, limit: int = MAX_SPANS_PER_PAGE) -> list[Span]:
        """Spans of the non blank lines, at most ``limit``; a bound, not a cut of text."""
        found: list[Span] = []
        offset = 0
        for line in self.normalized_text.split("\n"):
            if line and len(found) < limit:
                found.append(Span(self.page_number, offset, offset + len(line)))
            offset += len(line) + 1
        return found

    def quote(self, span: Span) -> str:
        """The exact text of ``span``; a span from another page or range is an error."""
        if span.page_number != self.page_number:
            raise ValueError("span belongs to another page")
        if not 0 <= span.start < span.end <= len(self.normalized_text):
            raise ValueError("span is outside the page text")
        return self.normalized_text[span.start : span.end]

    def to_json(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "normalized_text": self.normalized_text,
            "source_kind": self.source_kind,
            "quality_code": self.quality_code,
            "text_digest": self.text_digest,
        }


def text_digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_pages(
    raw: object, *, page_count: int, max_text_bytes: int
) -> tuple[ParsedPage, ...] | None:
    """Validate the child's ``pages`` list; ``None`` means reject the whole result."""
    if not isinstance(raw, list):
        return None
    items = cast("list[object]", raw)
    if len(items) != page_count:
        return None
    pages: list[ParsedPage] = []
    total = 0
    for expected, item in enumerate(items, start=1):
        page = _page(item, expected)
        if page is None:
            return None
        total += len(page.normalized_text.encode("utf-8"))
        if total > max_text_bytes:
            return None
        pages.append(page)
    return tuple(pages)


def _page(item: object, expected_number: int) -> ParsedPage | None:
    if not isinstance(item, Mapping):
        return None
    value = cast("Mapping[str, Any]", item)
    text = value.get("normalized_text")
    if value.get("page_number") != expected_number or not isinstance(text, str):
        return None
    if any(unicodedata.category(c) in _FORBIDDEN and c != "\n" for c in text):
        return None
    if text != text.strip() or unicodedata.normalize("NFKC", text) != text:
        return None
    quality = "has_text" if text else "empty"
    if value.get("quality_code") != quality:
        return None
    digest = value.get("text_digest")
    if digest != text_digest(text):
        return None
    return ParsedPage(expected_number, text, "native", quality, text_digest(text))


def has_native_text(pages: Sequence[ParsedPage]) -> bool:
    """True when at least one page carries text. Empty text is a scan candidate only."""
    return any(page.quality_code == "has_text" for page in pages)

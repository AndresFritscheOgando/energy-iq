"""Synthetic PDF builders for the native text tests and benchmark.

Everything here is invented. No real bill, name, address, or account number
ever enters the repository (spec 0012/0003). Text uses the standard Helvetica
font with WinAnsi encoding, so Spanish accents work and no font file is needed.
"""

import io
from collections.abc import Sequence

from pypdf import PdfWriter
from pypdf.generic import (
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

LEADING = 16


def _escape(line: str) -> bytes:
    raw = line.encode("cp1252", errors="replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


def _text_stream(lines: Sequence[str], *, hidden: Sequence[str] = ()) -> bytes:
    out = [b"BT /F1 12 Tf 72 720 Td"]
    for line in lines:
        out.append(b"(" + _escape(line) + b") Tj 0 -%d Td" % LEADING)
    if hidden:  # render mode 3: present in the text layer, invisible on the page
        out.append(b"3 Tr")
        for line in hidden:
            out.append(b"(" + _escape(line) + b") Tj 0 -%d Td" % LEADING)
    out.append(b"ET")
    return b"\n".join(out)


def _font(writer: PdfWriter) -> object:
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
            NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
        }
    )
    return writer._add_object(font)  # pyright: ignore[reportPrivateUsage]


def _image(writer: PdfWriter) -> object:
    """A tiny gray gradient: pixels only, no glyphs and no text layer."""
    image = DecodedStreamObject()
    image.set_data(bytes((x * 4 + y * 4) % 256 for y in range(8) for x in range(8)))
    image.update(
        {
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(8),
            NameObject("/Height"): NumberObject(8),
            NameObject("/ColorSpace"): NameObject("/DeviceGray"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        }
    )
    return writer._add_object(image)  # pyright: ignore[reportPrivateUsage]


def build_pdf(
    pages: Sequence[Sequence[str] | None],
    *,
    rotate: int = 0,
    hidden: Sequence[str] = (),
) -> bytes:
    """One page per entry: lines of text, or ``None`` for an image only scan.

    ``hidden`` lines are added invisibly to the first text page, and ``rotate``
    sets the page rotation (a multiple of 90).
    """
    writer = PdfWriter()
    font = _font(writer)
    image = _image(writer)
    hidden_done = False
    for lines in pages:
        page = writer.add_blank_page(width=612, height=792)
        if rotate:
            page[NameObject("/Rotate")] = NumberObject(rotate)
        resources = DictionaryObject()
        stream = DecodedStreamObject()
        if lines is None:
            resources[NameObject("/XObject")] = DictionaryObject(
                {NameObject("/Im1"): image}
            )
            stream.set_data(b"q 400 0 0 400 100 200 cm /Im1 Do Q")
        else:
            resources[NameObject("/Font")] = DictionaryObject({NameObject("/F1"): font})
            extra = () if hidden_done else hidden
            hidden_done = hidden_done or bool(hidden)
            stream.set_data(_text_stream(lines, hidden=extra))
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = writer._add_object(stream)  # pyright: ignore[reportPrivateUsage]
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()

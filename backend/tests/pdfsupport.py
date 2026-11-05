"""Synthetic PDFs for document tests. Never a real bill."""

import io

from pypdf import PdfWriter


def make_pdf(pages: int = 1, *, password: str | None = None) -> bytes:
    """A blank, valid PDF with ``pages`` pages, optionally encrypted."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if password is not None:
        writer.encrypt(user_password=password, owner_password=password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


# Starts and ends like a PDF but has no structure behind it.
MALFORMED_PDF = b"%PDF-1.4\n1 0 obj << /Broken\n%%EOF\n"
NOT_A_PDF = b"just some text, not a pdf at all"


def multipart(
    data: bytes,
    *,
    filename: str = "bill.pdf",
    content_type: str = "application/pdf",
    field: str = "file",
) -> dict[str, tuple[str, bytes, str]]:
    """The ``files`` argument for a test client upload."""
    return {field: (filename, data, content_type)}

"""Streaming PDF upload reader (spec 0012/0002 AC-1).

The body is parsed as it arrives and the file part is written straight to a
temporary name in the document root, so nothing is spooled elsewhere and a
rejected stream leaves no file. Size is counted from the bytes received,
never from a header. The client's file name is only checked for a ``.pdf``
ending and is never stored or used in a path.

Cheap checks run here: part count and name, extension, part content type,
the ``%PDF-`` signature, and an ``%%EOF`` marker near the end. The structural
checks (encrypted, malformed, page count) need a real parser, which must not
run in the API process, so the isolated child makes them (spec 0003 and the
worker) and fails the run with a stable code.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import IO

from python_multipart.exceptions import FormParserError
from python_multipart.multipart import MultipartParser, parse_options_header
from starlette.requests import Request

from energyiq.documents.storage import DocumentStore
from energyiq.platform.http.problems import ProblemError

PDF_SIGNATURE = b"%PDF-"
PDF_EOF_MARKER = b"%%EOF"
EOF_WINDOW = 1024  # the PDF spec allows trailing bytes after the marker
MULTIPART_OVERHEAD_BYTES = 64 * 1024
MAX_HEADER_BYTES = 1024
FILE_FIELD = "file"


@dataclass(frozen=True)
class ReceivedUpload:
    temp: Path
    sha256: bytes
    size: int


class _Collector:
    """Parser callbacks; every rejection is a ``ProblemError``."""

    def __init__(self, store: DocumentStore, max_bytes: int) -> None:
        self.store = store
        self.max_bytes = max_bytes
        self.parts = 0
        self.size = 0
        self.digest = hashlib.sha256()
        self.temp: Path | None = None
        self.handle: IO[bytes] | None = None
        self._field = b""
        self._value = b""
        self._headers: dict[bytes, bytes] = {}

    def on_part_begin(self) -> None:
        self.parts += 1
        if self.parts > 1:
            raise ProblemError(422, "upload_invalid")
        self._headers = {}

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._field += data[start:end]
        if len(self._field) > MAX_HEADER_BYTES:
            raise ProblemError(422, "upload_invalid")

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._value += data[start:end]
        if len(self._value) > MAX_HEADER_BYTES:
            raise ProblemError(422, "upload_invalid")

    def on_header_end(self) -> None:
        self._headers[self._field.lower()] = self._value
        self._field = b""
        self._value = b""

    def on_headers_finished(self) -> None:
        disposition = self._headers.get(b"content-disposition")
        if disposition is None:
            raise ProblemError(422, "upload_invalid")
        kind, options = parse_options_header(disposition)
        if kind != b"form-data" or options.get(b"name") != FILE_FIELD.encode():
            raise ProblemError(422, "upload_invalid")
        filename = options.get(b"filename")
        part_type = self._headers.get(b"content-type", b"").split(b";")[0]
        if (
            filename is None
            or not filename.lower().endswith(b".pdf")
            or part_type.strip().lower() != b"application/pdf"
        ):
            raise ProblemError(415, "upload_not_pdf")
        self.temp = self.store.new_temp()
        self.handle = self.temp.open("wb")

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        self.size += len(chunk)
        if self.size > self.max_bytes:
            raise ProblemError(413, "upload_too_large")
        assert self.handle is not None
        self.handle.write(chunk)
        self.digest.update(chunk)

    def close(self) -> None:
        if self.handle is not None:
            self.handle.close()
            self.handle = None

    def discard(self) -> None:
        self.close()
        if self.temp is not None:
            self.store.discard(self.temp)
            self.temp = None


def _boundary(request: Request) -> bytes:
    content_type = request.headers.get("content-type")
    if content_type is None:
        raise ProblemError(415, "unsupported_media_type")
    kind, options = parse_options_header(content_type)
    boundary = options.get(b"boundary")
    if kind != b"multipart/form-data" or not boundary:
        raise ProblemError(415, "unsupported_media_type")
    return boundary


def _check_pdf_shape(path: Path, size: int) -> None:
    with path.open("rb") as handle:
        if handle.read(len(PDF_SIGNATURE)) != PDF_SIGNATURE:
            raise ProblemError(422, "pdf_invalid")
        handle.seek(max(0, size - EOF_WINDOW))
        if PDF_EOF_MARKER not in handle.read():
            raise ProblemError(422, "pdf_invalid")


async def receive_pdf(
    request: Request, store: DocumentStore, max_bytes: int
) -> ReceivedUpload:
    """Stream one PDF part to a temporary file; discard it on any failure."""
    declared = request.headers.get("content-length")
    if (
        declared is not None
        and declared.isdigit()
        and int(declared) > max_bytes + MULTIPART_OVERHEAD_BYTES
    ):
        raise ProblemError(413, "upload_too_large")
    boundary = _boundary(request)
    collector = _Collector(store, max_bytes)
    parser = MultipartParser(
        boundary,
        {
            "on_part_begin": collector.on_part_begin,
            "on_header_field": collector.on_header_field,
            "on_header_value": collector.on_header_value,
            "on_header_end": collector.on_header_end,
            "on_headers_finished": collector.on_headers_finished,
            "on_part_data": collector.on_part_data,
        },
        max_size=max_bytes + MULTIPART_OVERHEAD_BYTES,
    )
    try:
        async for chunk in request.stream():
            parser.write(chunk)
        parser.finalize()
        collector.close()
        if collector.temp is None or collector.size == 0:
            raise ProblemError(422, "upload_invalid")
        _check_pdf_shape(collector.temp, collector.size)
    except FormParserError:
        collector.discard()
        raise ProblemError(422, "upload_invalid") from None
    except BaseException:
        collector.discard()
        raise
    return ReceivedUpload(collector.temp, collector.digest.digest(), collector.size)

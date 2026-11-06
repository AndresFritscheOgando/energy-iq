"""Private local document store (spec 0012/0002 AC-1, AC-4).

Files live under ``<root>/objects/<uuid>``; the name is a server generated
UUID and nothing a client sent ever reaches a path. Uploads are written to
``<root>/tmp`` first and renamed into ``objects`` only after every check
passes, so a rejected upload leaves no file. Both directories share one
filesystem, which makes the rename atomic. Moving to object storage later
means another class with the same methods.
"""

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4

OBJECTS = "objects"
TEMP = "tmp"
TEMP_SUFFIX = ".part"


class DocumentStore(Protocol):
    """What the routes, the worker, and the reconciler need from storage."""

    def new_temp(self) -> Path: ...
    def commit(self, temp: Path, key: UUID) -> None: ...
    def discard(self, temp: Path) -> None: ...
    def read(self, key: UUID) -> bytes: ...
    def open_path(self, key: UUID) -> Path: ...
    def exists(self, key: UUID) -> bool: ...
    def delete(self, key: UUID) -> bool: ...
    def keys(self) -> Iterator[UUID]: ...
    def temp_files(self) -> Iterator[Path]: ...


class LocalDocumentStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def _objects(self) -> Path:
        return self.root / OBJECTS

    @property
    def _temp(self) -> Path:
        return self.root / TEMP

    def _prepare(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):  # no POSIX modes on Windows
            directory.chmod(0o700)

    def _path(self, key: UUID) -> Path:
        return self._objects / str(key)

    def new_temp(self) -> Path:
        self._prepare(self._temp)
        return self._temp / f"{uuid4()}{TEMP_SUFFIX}"

    def commit(self, temp: Path, key: UUID) -> None:
        self._prepare(self._objects)
        os.replace(temp, self._path(key))

    def discard(self, temp: Path) -> None:
        with contextlib.suppress(FileNotFoundError):
            temp.unlink()

    def read(self, key: UUID) -> bytes:
        return self._path(key).read_bytes()

    def open_path(self, key: UUID) -> Path:
        return self._path(key)

    def exists(self, key: UUID) -> bool:
        return self._path(key).is_file()

    def delete(self, key: UUID) -> bool:
        """Remove the file; ``False`` when it was already absent."""
        try:
            self._path(key).unlink()
        except FileNotFoundError:
            return False
        return True

    def keys(self) -> Iterator[UUID]:
        """Every stored key; names that are not UUIDs are ignored."""
        if not self._objects.is_dir():
            return
        for entry in self._objects.iterdir():
            try:
                yield UUID(entry.name)
            except ValueError:
                continue

    def temp_files(self) -> Iterator[Path]:
        if self._temp.is_dir():
            yield from (
                entry
                for entry in self._temp.iterdir()
                if entry.name.endswith(TEMP_SUFFIX)
            )

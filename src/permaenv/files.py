"""Bounded POSIX file operations. Close target applications before mutation.

Directory descriptors prevent symlink traversal. Preconditions catch observable
changes, but cannot make read/check/replace atomic against unrelated writers.
"""

import errno
import hashlib
import os
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType

from permaenv.errors import HistoryError
from permaenv.models import FileState, validate_relative_path

__all__ = ["ConfinedFiles", "FileState", "validate_relative_path"]


@dataclass(frozen=True)
class CapturedFile:
    state: FileState
    data: bytes | None


def _error(exc: OSError) -> HistoryError:
    if isinstance(exc, PermissionError) or exc.errno in {errno.EACCES, errno.EPERM}:
        return HistoryError("inaccessible", "Selected file or directory is inaccessible")
    return HistoryError("filesystem_error", "File operation failed")


def _signature(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


class ConfinedFiles:
    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        self.fd: int | None = None

    def __enter__(self) -> "ConfinedFiles":
        try:
            parent = self._open_directory("/", None)
            try:
                for part in self.root.parts[1:]:
                    child = self._open_directory(part, parent)
                    os.close(parent)
                    parent = child
                self.fd = parent
            except BaseException:
                os.close(parent)
                raise
        except FileNotFoundError:
            raise HistoryError("missing_root", "Capture root must exist") from None
        except OSError as exc:
            raise _error(exc) from None
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    @staticmethod
    def _open_directory(path: str, parent: int | None) -> int:
        before = os.stat(path, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISLNK(before.st_mode):
            raise HistoryError("symlink", "Symlinks are not allowed")
        if not stat.S_ISDIR(before.st_mode):
            raise HistoryError("special_file", "Parent must be a directory")
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        if (before.st_dev, before.st_ino) != (os.fstat(fd).st_dev, os.fstat(fd).st_ino):
            os.close(fd)
            raise HistoryError("unstable_file", "Directory changed during access")
        return fd

    @contextmanager
    def _parent(self, path: str) -> Iterator[tuple[int, str]]:
        parts = validate_relative_path(path).split("/")
        if self.fd is None:
            raise HistoryError("closed_root", "File root is not open")
        opened: list[int] = []
        parent = self.fd
        try:
            for part in parts[:-1]:
                try:
                    parent = self._open_directory(part, parent)
                except FileNotFoundError:
                    raise HistoryError(
                        "missing_parent", "Selected parent directory must exist"
                    ) from None
                opened.append(parent)
            yield parent, parts[-1]
        except OSError as exc:
            raise _error(exc) from None
        finally:
            for fd in reversed(opened):
                os.close(fd)

    def _read_at(self, parent: int, leaf: str) -> CapturedFile:
        try:
            before = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return CapturedFile(FileState.absent(), None)
        if stat.S_ISLNK(before.st_mode):
            raise HistoryError("symlink", "Symlinks are not allowed")
        if not stat.S_ISREG(before.st_mode):
            raise HistoryError("special_file", "Selected leaf must be a regular file")
        try:
            fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            raise HistoryError("unstable_file", "Selected file changed during capture") from None
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode) or _signature(before) != _signature(opened):
                raise HistoryError("unstable_file", "Selected file changed during capture")
            chunks = []
            while chunk := os.read(fd, 1024 * 1024):
                chunks.append(chunk)
            data = b"".join(chunks)
            after = os.fstat(fd)
            try:
                current = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                raise HistoryError(
                    "unstable_file", "Selected file changed during capture"
                ) from None
            if (
                _signature(before) != _signature(after)
                or _signature(after) != _signature(current)
                or len(data) != after.st_size
            ):
                raise HistoryError("unstable_file", "Selected file changed during capture")
            return CapturedFile(
                FileState(
                    True,
                    hashlib.sha256(data).hexdigest(),
                    len(data),
                    stat.S_IMODE(after.st_mode) & 0o777,
                ),
                data,
            )
        finally:
            os.close(fd)

    def _check_parent(self, path: str, parent: int) -> None:
        # Reopen from the named root to detect a detached/relocated directory.
        with ConfinedFiles(self.root) as current, current._parent(path) as (fresh, _):
            old_stat, new_stat = os.fstat(parent), os.fstat(fresh)
            if (old_stat.st_dev, old_stat.st_ino) != (new_stat.st_dev, new_stat.st_ino):
                raise HistoryError("stale_state", "Selected directory changed during access", 3)

    def read(self, path: str) -> CapturedFile:
        with self._parent(path) as (parent, leaf):
            captured = self._read_at(parent, leaf)
            self._check_parent(path, parent)
            return captured

    def check(self, path: str, expected: FileState) -> None:
        if self.read(path).state != expected:
            raise HistoryError("stale_state", "Selected file no longer matches expected state", 3)

    def write(self, path: str, data: bytes, mode: int, *, expected: FileState) -> FileState:
        if type(mode) is not int or not 0 <= mode <= 0o777:
            raise HistoryError("invalid_mode", "Invalid portable permissions", 2)
        with self._parent(path) as (parent, leaf):
            temporary = ".permaenv-" + uuid.uuid4().hex
            fd = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                0o600,
                dir_fd=parent,
            )
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fchmod(stream.fileno(), mode)
                    os.fsync(stream.fileno())
                if self._read_at(parent, leaf).state != expected:
                    raise HistoryError(
                        "stale_state", "Selected file no longer matches expected state", 3
                    )
                self._check_parent(path, parent)
                os.replace(temporary, leaf, src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent)
        return FileState(True, hashlib.sha256(data).hexdigest(), len(data), mode)

    def delete(self, path: str, *, expected: FileState) -> FileState:
        with self._parent(path) as (parent, leaf):
            if self._read_at(parent, leaf).state != expected:
                raise HistoryError(
                    "stale_state", "Selected file no longer matches expected state", 3
                )
            self._check_parent(path, parent)
            if expected.exists:
                os.unlink(leaf, dir_fd=parent)
                os.fsync(parent)
        return FileState.absent()

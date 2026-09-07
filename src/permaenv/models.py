"""Immutable local history records and strict on-disk validation."""

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from permaenv.errors import HistoryError


def validate_relative_path(path: str) -> str:
    if (
        not isinstance(path, str)
        or not path
        or path.startswith("/")
        or "\\" in path
        or "\x00" in path
        or any(p in {"", ".", ".."} for p in path.split("/"))
    ):
        raise HistoryError("invalid_path", "Expected a bounded relative file path", 2)
    if any(p in {".vscode", ".idea", ".mcp.json"} for p in path.split("/")):
        raise HistoryError("invalid_path", "Project configuration paths are excluded", 2)
    return path


def validate_name(name: str) -> str:
    if not isinstance(name, str) or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", name) is None:
        raise HistoryError("invalid_name", "Environment name must be a safe slug", 2)
    return name


def validate_id(value: str, prefix: str) -> str:
    if (
        not isinstance(value, str)
        or re.fullmatch(re.escape(prefix) + r"_[0-9a-f]{32}", value) is None
    ):
        raise HistoryError("invalid_id", f"Invalid {prefix} identifier", 2)
    return value


def record_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise HistoryError("invalid_record", "Expected a record object")
    return value


def string(value: object) -> str:
    if not isinstance(value, str):
        raise HistoryError("invalid_record", "Expected a string field")
    return value


def schema(record: dict[str, Any]) -> None:
    if type(record.get("schema_version")) is not int or record["schema_version"] != 1:
        raise HistoryError("invalid_record", "Unsupported record schema version")


@dataclass(frozen=True)
class FileState:
    exists: bool
    sha256: str | None
    size: int | None
    mode: int | None

    @classmethod
    def absent(cls) -> "FileState":
        return cls(False, None, None, None)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "FileState":
        d = record_dict(value)
        if d.get("exists") is False and d == cls.absent().to_dict():
            return cls.absent()
        sha, size, mode = d.get("sha256"), d.get("size"), d.get("mode")
        if (
            d.get("exists") is not True
            or not isinstance(sha, str)
            or re.fullmatch(r"[0-9a-f]{64}", sha) is None
            or type(size) is not int
            or size < 0
            or type(mode) is not int
            or not 0 <= mode <= 0o777
        ):
            raise HistoryError("invalid_record", "Invalid file state")
        return cls(True, sha, size, mode)


@dataclass(frozen=True)
class FileEntry:
    path: str
    state: FileState

    @classmethod
    def from_dict(cls, value: object) -> "FileEntry":
        d = record_dict(value)
        return cls(
            validate_relative_path(string(d.get("path"))), FileState.from_dict(d.get("state"))
        )


@dataclass(frozen=True)
class Environment:
    name: str
    root: str | None
    files: tuple[str, ...]
    adapter_id: str = "custom-files"
    adapter_version: int = 1
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "Environment":
        d = record_dict(value)
        schema(d)
        name = validate_name(string(d.get("name")))
        root = d.get("root")
        paths = d.get("files")
        if root is not None and (
            not isinstance(root, str) or not root.startswith("/") or "\x00" in root
        ):
            raise HistoryError("invalid_record", "Invalid capture root")
        if (
            not isinstance(paths, list)
            or d.get("adapter_id") != "custom-files"
            or type(d.get("adapter_version")) is not int
            or d.get("adapter_version") != 1
        ):
            raise HistoryError("invalid_record", "Invalid custom-files binding")
        files = tuple(validate_relative_path(string(p)) for p in paths)
        if len(set(files)) != len(files) or (files and root is None):
            raise HistoryError("invalid_record", "Invalid file selection")
        return cls(name, root, files)


@dataclass(frozen=True)
class Snapshot:
    id: str
    environment: str
    root: str
    entries: tuple[FileEntry, ...]
    created_at: str
    name: str | None = None
    adapter_id: str = "custom-files"
    adapter_version: int = 1
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: object) -> "Snapshot":
        d = record_dict(value)
        schema(d)
        entries = d.get("entries")
        if not isinstance(entries, list) or not entries:
            raise HistoryError("invalid_record", "Snapshot requires manifest entries")
        parsed = tuple(FileEntry.from_dict(e) for e in entries)
        binding = Environment.from_dict(
            {**d, "name": d.get("environment"), "files": [e.path for e in parsed]}
        )
        if binding.root is None:
            raise HistoryError("invalid_record", "Snapshot requires a root")
        name = d.get("name")
        if name is not None:
            name = string(name)
        return cls(
            validate_id(string(d.get("id")), "snap"),
            binding.name,
            binding.root,
            parsed,
            string(d.get("created_at")),
            name,
        )


@dataclass(frozen=True)
class DiffEntry:
    path: str
    status: Literal["added", "removed", "modified", "unchanged"]
    before: FileState
    after: FileState


@dataclass(frozen=True)
class Diff:
    from_id: str
    to_id: str | None
    entries: tuple[DiffEntry, ...]
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

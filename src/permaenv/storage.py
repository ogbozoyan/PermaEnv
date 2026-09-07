"""Private local records, content objects and durable operation journals."""

import fcntl
import hashlib
import json
import os
import platform
import re
import sqlite3
import stat
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from permaenv.errors import HistoryError
from permaenv.files import ConfinedFiles
from permaenv.models import record_dict, validate_id


def default_state_dir() -> Path:
    override = os.environ.get("PERMAENV_HOME")
    if override:
        return Path(override).expanduser().absolute()
    if platform.system() == "Darwin":
        return Path.home() / "Library/Application Support/PermaEnv"
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg.startswith("/") else Path.home() / ".local/share"
    return base / "permaenv"


def new_id(prefix: str) -> str:
    return validate_id(prefix + "_" + uuid.uuid4().hex, prefix)


def canonical_json(value: object) -> str:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def parse_json_record(value: str | bytes) -> dict[str, Any]:
    try:
        return record_dict(json.loads(value))
    except (ValueError, UnicodeError):
        raise HistoryError("invalid_record", "Invalid local JSON record") from None


@dataclass(frozen=True)
class RunRecord:
    id: str
    operation: str
    arguments: dict[str, Any]
    status: str
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    idempotency_key: str | None

    def to_dict(self) -> dict[str, Any]:
        from dataclasses import asdict

        return asdict(self)


class Store:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root if root is not None else default_state_dir()).expanduser().absolute()

    @staticmethod
    def _ensure_directory(name: str, parent: int) -> int:
        """Open or create exactly one component without following symlinks."""
        try:
            return ConfinedFiles._open_directory(name, parent)
        except FileNotFoundError:
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent)
            except FileExistsError:
                # Another initializer may have created it; still check no-follow.
                pass
            else:
                os.fsync(parent)
            return ConfinedFiles._open_directory(name, parent)

    def initialize(self) -> None:
        try:
            parent = ConfinedFiles._open_directory("/", None)
            try:
                for part in self.root.parts[1:]:
                    child = self._ensure_directory(part, parent)
                    os.close(parent)
                    parent = child
                os.fchmod(parent, 0o700)
                for name in ["environments", "snapshots", "plans", "objects"]:
                    child = self._ensure_directory(name, parent)
                    try:
                        os.fchmod(child, 0o700)
                    finally:
                        os.close(child)
            finally:
                os.close(parent)
        except OSError:
            raise HistoryError("store_error", "Cannot initialize local state directory") from None

    @contextmanager
    def lock(self) -> Iterator[None]:
        self.initialize()
        try:
            fd = os.open(
                self.root / "operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
            )
        except OSError:
            raise HistoryError("store_error", "Cannot open operation lock") from None
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise HistoryError("store_error", "Invalid operation lock")
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def read_bytes(self, relative: str) -> bytes:
        with ConfinedFiles(self.root) as files:
            captured = files.read(relative)
        if captured.data is None:
            raise HistoryError("not_found", "Local record does not exist")
        return captured.data

    def atomic_bytes(self, relative: str, data: bytes, *, overwrite: bool = True) -> None:
        with ConfinedFiles(self.root) as files:
            previous = files.read(relative)
            if previous.state.exists and not overwrite:
                raise HistoryError("already_exists", "Local record already exists")
            files.write(relative, data, 0o600, expected=previous.state)

    def atomic_json(self, relative: str, value: object, *, overwrite: bool = True) -> None:
        self.atomic_bytes(relative, canonical_json(value).encode(), overwrite=overwrite)

    def load_json(self, relative: str) -> dict[str, Any]:
        return parse_json_record(self.read_bytes(relative))

    def put_object(self, data: bytes) -> str:
        digest = hashlib.sha256(data).hexdigest()
        with ConfinedFiles(self.root) as files:
            previous = files.read("objects/" + digest)
            if previous.state.exists:
                if previous.data != data:
                    raise HistoryError("corrupt_object", "Content object failed hash verification")
            else:
                files.write("objects/" + digest, data, 0o600, expected=previous.state)
        return digest

    def read_object(self, digest: str | None) -> bytes:
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise HistoryError("invalid_id", "Invalid content object identifier", 2)
        try:
            data = self.read_bytes("objects/" + digest)
        except HistoryError as exc:
            if exc.code == "not_found":
                raise HistoryError("corrupt_object", "Content object is missing") from None
            raise
        if hashlib.sha256(data).hexdigest() != digest:
            raise HistoryError("corrupt_object", "Content object failed hash verification")
        return data

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """Caller holds lock; each successful context commits, errors roll back."""
        path = self.root / "runs.sqlite3"
        try:
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise HistoryError("store_error", "Invalid run database")
                os.fchmod(fd, 0o600)
            finally:
                os.close(fd)
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA foreign_keys=ON")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY, operation TEXT NOT NULL, arguments TEXT NOT NULL,
                    status TEXT NOT NULL, result TEXT, error TEXT,
                    idempotency_key TEXT UNIQUE);
                CREATE TABLE IF NOT EXISTS actions (
                    run_id TEXT NOT NULL REFERENCES runs(id), sequence INTEGER NOT NULL,
                    status TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence));
            """)
            try:
                with connection:
                    yield connection
            finally:
                connection.close()
        except (OSError, sqlite3.Error):
            raise HistoryError("store_error", "Local run database operation failed") from None

    @staticmethod
    def _run(row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            row["id"],
            row["operation"],
            parse_json_record(row["arguments"]),
            row["status"],
            parse_json_record(row["result"]) if row["result"] else None,
            parse_json_record(row["error"]) if row["error"] else None,
            row["idempotency_key"],
        )

    def begin_run(
        self, operation: str, arguments: dict[str, Any], idempotency_key: str | None = None
    ) -> tuple[RunRecord, bool]:
        """Return (run, reused). A reused failed/pending run MUST NOT execute again."""
        if idempotency_key is not None and (
            not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 256
        ):
            raise HistoryError("invalid_idempotency_key", "Invalid idempotency key", 2)
        encoded = canonical_json(arguments)
        with self.connection() as conn:
            if idempotency_key is not None:
                row = conn.execute(
                    "SELECT * FROM runs WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                if row is not None:
                    if row["operation"] != operation or row["arguments"] != encoded:
                        raise HistoryError(
                            "idempotency_conflict", "Idempotency key has different arguments", 3
                        )
                    return self._run(row), True
            run_id = new_id("run")
            conn.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, NULL, NULL, ?)",
                (run_id, operation, encoded, "pending", idempotency_key),
            )
        return self.get_run(run_id), False

    def get_run(self, run_id: str) -> RunRecord:
        validate_id(run_id, "run")
        with self.connection() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
            if row is None:
                raise HistoryError("not_found", "Run does not exist")
            return self._run(row)

    def finish_run(
        self,
        run_id: str,
        status: str,
        *,
        result: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
    ) -> None:
        validate_id(run_id, "run")
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE runs SET status=?, result=?, error=? WHERE id=?",
                (
                    status,
                    canonical_json(result) if result is not None else None,
                    canonical_json(error) if error is not None else None,
                    run_id,
                ),
            )
            if cursor.rowcount != 1:
                raise HistoryError("not_found", "Run does not exist")

    def record_action(
        self, run_id: str, sequence: int, payload: dict[str, Any], status: str = "pending"
    ) -> None:
        """Durably insert previous/post states BEFORE the caller mutates a target."""
        validate_id(run_id, "run")
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO actions VALUES (?, ?, ?, ?)",
                (run_id, sequence, status, canonical_json(payload)),
            )

    def update_action(self, run_id: str, sequence: int, status: str) -> None:
        validate_id(run_id, "run")
        with self.connection() as conn:
            cursor = conn.execute(
                "UPDATE actions SET status=? WHERE run_id=? AND sequence=?",
                (status, run_id, sequence),
            )
            if cursor.rowcount != 1:
                raise HistoryError("not_found", "Run action does not exist")

    def list_actions(self, run_id: str) -> list[dict[str, Any]]:
        validate_id(run_id, "run")
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM actions WHERE run_id=? ORDER BY sequence", (run_id,)
            ).fetchall()
            return [
                {
                    "sequence": row["sequence"],
                    "status": row["status"],
                    "payload": parse_json_record(row["payload"]),
                }
                for row in rows
            ]

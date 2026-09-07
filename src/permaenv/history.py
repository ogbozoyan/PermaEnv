"""Application service for explicit environments and immutable local snapshots."""

import json
import tomllib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from permaenv.errors import HistoryError
from permaenv.files import ConfinedFiles
from permaenv.models import (
    Diff,
    DiffEntry,
    Environment,
    FileEntry,
    Snapshot,
    schema,
    string,
    validate_id,
    validate_name,
    validate_relative_path,
)
from permaenv.storage import Store, new_id


class HistoryService:
    def __init__(self, state_dir: Path | None = None) -> None:
        self.store = Store(state_dir)

    def _validate_root(self, root: Path) -> Path:
        absolute = root.expanduser().absolute()
        resolved = absolute.resolve()
        state = self.store.root.resolve()
        if resolved == state or resolved.is_relative_to(state) or state.is_relative_to(resolved):
            raise HistoryError(
                "root_overlap", "Capture root and state directory must not overlap", 2
            )
        with ConfinedFiles(absolute):
            pass
        return absolute

    def create_environment(
        self,
        name: str,
        root: Path | None = None,
        files: Sequence[str] = (),
        *,
        select: bool = False,
    ) -> Environment:
        validate_name(name)
        paths = tuple(validate_relative_path(p) for p in files)
        if len(set(paths)) != len(paths):
            raise HistoryError("invalid_path", "Selected file paths must be unique", 2)
        if paths and root is None:
            raise HistoryError("missing_root", "File selection requires a root", 2)
        absolute = self._validate_root(root) if root is not None else None
        environment = Environment(name, str(absolute) if absolute is not None else None, paths)
        if absolute is not None:
            with ConfinedFiles(absolute) as confined:
                for path in paths:
                    confined.read(path)
        with self.store.lock():
            # JSON string syntax is also valid for these TOML strings/arrays.
            values = environment.to_dict()
            document = (
                "\n".join(
                    f"{key} = {json.dumps(value)}"
                    for key, value in values.items()
                    if value is not None
                )
                + "\n"
            )
            self.store.atomic_bytes(f"environments/{name}.toml", document.encode(), overwrite=False)
            if select:
                self.store.atomic_json("selection.json", {"schema_version": 1, "environment": name})
        return environment

    def _get_environment(self, name: str | None = None) -> Environment:
        if name is None:
            try:
                selection = self.store.load_json("selection.json")
            except HistoryError as exc:
                if exc.code == "not_found":
                    raise HistoryError(
                        "no_environment_selected", "Select an environment first", 3
                    ) from None
                raise
            schema(selection)
            name = string(selection.get("environment"))
        validate_name(name)
        try:
            document = tomllib.loads(self.store.read_bytes(f"environments/{name}.toml").decode())
        except (ValueError, UnicodeError):
            raise HistoryError("invalid_record", "Invalid environment record") from None
        environment = Environment.from_dict(document)
        if environment.name != name:
            raise HistoryError("invalid_record", "Environment identity does not match its record")
        return environment

    def get_environment(self, name: str | None = None) -> Environment:
        if name is not None:
            validate_name(name)
        with self.store.lock():
            return self._get_environment(name)

    def list_environments(self) -> list[Environment]:
        with self.store.lock():
            return [
                self._get_environment(path.stem)
                for path in sorted((self.store.root / "environments").glob("*.toml"))
            ]

    def use_environment(self, name: str) -> Environment:
        validate_name(name)
        with self.store.lock():
            environment = self._get_environment(name)
            self.store.atomic_json("selection.json", {"schema_version": 1, "environment": name})
            return environment

    def _capture(self, environment: Environment, *, persist: bool = True) -> tuple[FileEntry, ...]:
        if environment.root is None or not environment.files:
            raise HistoryError("empty_environment", "Empty environment cannot be snapshotted", 3)
        root = self._validate_root(Path(environment.root))
        entries = []
        with ConfinedFiles(root) as files:
            for path in environment.files:
                captured = files.read(validate_relative_path(path))
                if persist and captured.data is not None:
                    self.store.put_object(captured.data)
                entries.append(FileEntry(path, captured.state))
        return tuple(entries)

    def snapshot(
        self,
        environment: str | None = None,
        *,
        name: str | None = None,
        idempotency_key: str | None = None,
    ) -> Snapshot:
        if name is not None and (not isinstance(name, str) or not name or len(name) > 256):
            raise HistoryError("invalid_name", "Snapshot name must contain 1 to 256 characters", 2)
        with self.store.lock():
            binding = self._get_environment(environment)
            if binding.root is None or not binding.files:
                raise HistoryError(
                    "empty_environment", "Empty environment cannot be snapshotted", 3
                )
            run, reused = self.store.begin_run(
                "snapshot", {"environment": binding.to_dict(), "name": name}, idempotency_key
            )
            if reused:
                if run.status != "succeeded" or run.result is None:
                    raise HistoryError(
                        "previous_run_failed",
                        "Previous run failed or was interrupted; inspect the run",
                        3,
                    )
                return self._get_snapshot(string(run.result.get("snapshot_id")))
            try:
                entries = self._capture(binding)
                snapshot = Snapshot(
                    new_id("snap"),
                    binding.name,
                    binding.root,
                    entries,
                    datetime.now(UTC).isoformat(),
                    name,
                )
                self.store.atomic_json(
                    f"snapshots/{snapshot.id}.json", snapshot.to_dict(), overwrite=False
                )
                self.store.finish_run(run.id, "succeeded", result={"snapshot_id": snapshot.id})
                return snapshot
            except BaseException as exc:
                error = (
                    exc
                    if isinstance(exc, HistoryError)
                    else HistoryError("capture_failed", "Snapshot capture failed")
                )
                self.store.finish_run(run.id, "failed", error=error.to_dict())
                raise

    def _get_snapshot(self, snapshot_id: str) -> Snapshot:
        validate_id(snapshot_id, "snap")
        snapshot = Snapshot.from_dict(self.store.load_json(f"snapshots/{snapshot_id}.json"))
        if snapshot.id != snapshot_id:
            raise HistoryError("invalid_record", "Snapshot identity does not match its record")
        return snapshot

    def get_snapshot(self, snapshot_id: str) -> Snapshot:
        validate_id(snapshot_id, "snap")
        with self.store.lock():
            return self._get_snapshot(snapshot_id)

    def list_snapshots(self, environment: str | None = None) -> list[Snapshot]:
        with self.store.lock():
            binding = self._get_environment(environment)
            snapshots = [
                self._get_snapshot(path.stem)
                for path in (self.store.root / "snapshots").glob("*.json")
            ]
            return sorted(
                (s for s in snapshots if s.environment == binding.name),
                key=lambda s: (s.created_at, s.id),
            )

    @staticmethod
    def _diff(before: Snapshot, after: tuple[FileEntry, ...], to_id: str | None) -> Diff:
        if tuple(e.path for e in before.entries) != tuple(e.path for e in after):
            raise HistoryError(
                "incompatible_selection", "Snapshots have different file selections", 2
            )
        entries = []
        for old, new in zip(before.entries, after, strict=True):
            status: Literal["added", "removed", "modified", "unchanged"] = (
                "unchanged"
                if old.state == new.state
                else "added"
                if not old.state.exists
                else "removed"
                if not new.state.exists
                else "modified"
            )
            entries.append(DiffEntry(old.path, status, old.state, new.state))
        return Diff(before.id, to_id, tuple(entries))

    def diff_live(self, snapshot_id: str) -> Diff:
        validate_id(snapshot_id, "snap")
        with self.store.lock():
            snapshot = self._get_snapshot(snapshot_id)
            binding = Environment(
                snapshot.environment, snapshot.root, tuple(e.path for e in snapshot.entries)
            )
            return self._diff(snapshot, self._capture(binding, persist=False), None)

    def diff_snapshots(self, from_id: str, to_id: str) -> Diff:
        validate_id(from_id, "snap")
        validate_id(to_id, "snap")
        with self.store.lock():
            before, after = self._get_snapshot(from_id), self._get_snapshot(to_id)
            if (before.root, before.adapter_id, before.adapter_version) != (
                after.root,
                after.adapter_id,
                after.adapter_version,
            ):
                raise HistoryError(
                    "incompatible_selection", "Snapshots have incompatible bindings", 2
                )
            return self._diff(before, after.entries, after.id)

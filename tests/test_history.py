import json
import os
from pathlib import Path

import pytest

from permaenv.errors import HistoryError
from permaenv.history import HistoryService


@pytest.fixture
def service(tmp_path: Path) -> HistoryService:
    return HistoryService(tmp_path / "state")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    path = tmp_path / "root"
    path.mkdir()
    (path / "nested").mkdir()
    (path / "a").write_bytes(b"same")
    (path / "nested/b").write_bytes(b"same")
    return path


def test_snapshot_diff_immutability_and_deduplication(service: HistoryService, root: Path):
    env = service.create_environment("work", root, ["a", "nested/b", "absent"], select=True)
    assert service.get_environment() == env
    first = service.snapshot(name="original")
    assert first.adapter_id == "custom-files"
    assert first.entries[2].state.exists is False
    assert len(list((service.store.root / "objects").iterdir())) == 1
    (root / "a").write_bytes(b"changed")
    (root / "nested/b").unlink()
    (root / "absent").write_bytes(b"new")
    assert [entry.status for entry in service.diff_live(first.id).entries] == [
        "modified",
        "removed",
        "added",
    ]
    second = service.snapshot()
    assert (
        service.diff_snapshots(first.id, second.id).entries == service.diff_live(first.id).entries
    )
    assert service.get_snapshot(first.id) == first
    assert service.list_snapshots() == [first, second]
    assert service.store.read_object(first.entries[0].state.sha256) == b"same"
    assert json.loads(json.dumps(first.to_dict()))["schema_version"] == 1
    assert (service.store.root.stat().st_mode & 0o777) == 0o700
    assert (service.store.root / "environments/work.toml").is_file()


def test_mode_only_diff_and_empty_environment(service: HistoryService, root: Path):
    service.create_environment("empty")
    with pytest.raises(HistoryError):
        service.snapshot("empty")
    service.create_environment("work", root, ["a"], select=True)
    first = service.snapshot()
    os.chmod(root / "a", 0o700)
    entry = service.diff_live(first.id).entries[0]
    assert entry.status == "modified"
    assert entry.before.sha256 == entry.after.sha256
    assert entry.before.mode != entry.after.mode
    assert service.list_environments()[0].name == "empty"
    service.use_environment("empty")
    assert service.get_environment().name == "empty"
    with pytest.raises(HistoryError):
        service.create_environment("work")


def test_snapshot_idempotency_returns_original_after_live_change(
    service: HistoryService, root: Path
):
    service.create_environment("work", root, ["a"], select=True)
    first = service.snapshot(name="one", idempotency_key="retry")
    (root / "a").write_bytes(b"changed")
    assert service.snapshot(name="one", idempotency_key="retry") == first
    with pytest.raises(HistoryError) as exc:
        service.snapshot(name="different", idempotency_key="retry")
    assert exc.value.code == "idempotency_conflict"
    assert len(service.list_snapshots()) == 1


@pytest.mark.parametrize("name", ["", "../x", "/x", "a/b", ".hidden", "bad name"])
def test_invalid_environment_names(service: HistoryService, name: str):
    with pytest.raises(HistoryError):
        service.create_environment(name)


@pytest.mark.parametrize("path", ["/etc/passwd", "../x", ".idea/a", "nested/.mcp.json"])
def test_path_validation_precedes_root_access(service: HistoryService, path: str):
    with pytest.raises(HistoryError) as exc:
        service.create_environment("work", Path("/does-not-exist"), [path])
    assert exc.value.code == "invalid_path"


def test_overlap_in_either_direction_rejected(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "inner").mkdir()
    for root in [tmp_path, state, state / "inner"]:
        with pytest.raises(HistoryError) as exc:
            HistoryService(state).create_environment("work", root, ["x"])
        assert exc.value.code == "root_overlap"


@pytest.mark.parametrize("value", ["../../x", "/tmp/x", "snap_bad", "env_" + "a" * 32])
def test_invalid_snapshot_ids(service: HistoryService, value: str):
    with pytest.raises(HistoryError) as exc:
        service.get_snapshot(value)
    assert exc.value.code == "invalid_id"


def test_corrupt_objects_and_incompatible_selection(service: HistoryService, root: Path):
    service.create_environment("work", root, ["a"], select=True)
    first = service.snapshot()
    service.create_environment("other", root, ["nested/b"])
    second = service.snapshot("other")
    with pytest.raises(HistoryError) as exc:
        service.diff_snapshots(first.id, second.id)
    assert exc.value.code == "incompatible_selection"
    (service.store.root / "objects" / first.entries[0].state.sha256).write_bytes(b"corrupt")
    with pytest.raises(HistoryError) as exc:
        service.store.read_object(first.entries[0].state.sha256)
    assert exc.value.code == "corrupt_object"


def test_saved_paths_are_revalidated(service: HistoryService, root: Path):
    service.create_environment("work", root, ["a"], select=True)
    snap = service.snapshot()
    path = service.store.root / "snapshots" / f"{snap.id}.json"
    record = json.loads(path.read_text())
    record["entries"][0]["path"] = "../escape"
    path.write_text(json.dumps(record))
    with pytest.raises(HistoryError):
        service.get_snapshot(snap.id)


def test_state_resolution_is_lazy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    override = tmp_path / "override"
    monkeypatch.setenv("PERMAENV_HOME", str(override))
    service = HistoryService()
    assert service.store.root == override
    assert not override.exists()


def test_live_diff_does_not_store_new_content(service: HistoryService, root: Path):
    service.create_environment("work", root, ["a"], select=True)
    snap = service.snapshot()
    before = list((service.store.root / "objects").iterdir())
    (root / "a").write_bytes(b"new")
    assert service.diff_live(snap.id).entries[0].status == "modified"
    assert list((service.store.root / "objects").iterdir()) == before


def test_failed_snapshot_is_durable_and_not_retried(service: HistoryService, root: Path):
    service.create_environment("work", root, ["a"], select=True)
    (root / "a").unlink()
    (root / "a").symlink_to("nested/b")
    with pytest.raises(HistoryError):
        service.snapshot(idempotency_key="failed")
    (root / "a").unlink()
    (root / "a").write_bytes(b"fixed")
    with pytest.raises(HistoryError) as exc:
        service.snapshot(idempotency_key="failed")
    assert exc.value.code == "previous_run_failed"
    assert service.list_snapshots() == []
    with service.store.lock(), service.store.connection() as conn:
        row = conn.execute("SELECT status, error FROM runs").fetchone()
        assert row["status"] == "failed"
        assert json.loads(row["error"])["code"] == "symlink"


def test_pending_runs_and_actions_survive_reopening(service: HistoryService):
    with service.store.lock():
        run, reused = service.store.begin_run("restore", {"plan": "test"}, "key")
        assert not reused
        service.store.record_action(run.id, 0, {"path": "a", "before": {"exists": False}})
    reopened = HistoryService(service.store.root)
    with reopened.store.lock():
        previous, reused = reopened.store.begin_run("restore", {"plan": "test"}, "key")
        assert reused and previous.id == run.id and previous.status == "pending"
        assert reopened.store.list_actions(run.id)[0]["payload"]["path"] == "a"
        reopened.store.update_action(run.id, 0, "applied")
        reopened.store.finish_run(run.id, "succeeded", result={"changed": 1})
        assert reopened.store.get_run(run.id).result == {"changed": 1}
        assert reopened.store.list_actions(run.id)[0]["status"] == "applied"
        with pytest.raises(HistoryError) as exc:
            reopened.store.begin_run("rollback", {"plan": "test"}, "key")
        assert exc.value.code == "idempotency_conflict"


def test_selection_schema_version_rejected(service: HistoryService, root: Path):
    service.create_environment("work", root, ["a"], select=True)
    (service.store.root / "selection.json").write_text(
        '{"schema_version": 999, "environment": "work"}'
    )
    with pytest.raises(HistoryError) as exc:
        service.get_environment()
    assert exc.value.code == "invalid_record"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.update(schema_version=2),
        lambda d: d.update(adapter_version=True),
        lambda d: d["entries"][0]["state"].update(mode=True),
        lambda d: d["entries"][0]["state"].update(sha256="../invalid"),
        lambda d: d["entries"][0].update(
            state={"exists": 0, "sha256": None, "mode": None, "size": None}
        ),
    ],
)
def test_invalid_saved_snapshot_fields_rejected(service: HistoryService, root: Path, mutate):
    service.create_environment("work", root, ["a"], select=True)
    snap = service.snapshot()
    path = service.store.root / "snapshots" / f"{snap.id}.json"
    value = json.loads(path.read_text())
    mutate(value)
    path.write_text(json.dumps(value))
    with pytest.raises(HistoryError):
        service.get_snapshot(snap.id)


def test_linux_state_defaults_ignore_relative_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PERMAENV_HOME", raising=False)
    monkeypatch.setattr("permaenv.storage.platform.system", lambda: "Linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("XDG_DATA_HOME", "relative")
    assert HistoryService().store.root == tmp_path / ".local/share/permaenv"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert HistoryService().store.root == tmp_path / "xdg/permaenv"
    monkeypatch.setattr("permaenv.storage.platform.system", lambda: "Darwin")
    assert HistoryService().store.root == tmp_path / "Library/Application Support/PermaEnv"
    assert list(tmp_path.iterdir()) == []


def test_unchanged_files_and_explicit_absence_remain_in_manifest(
    service: HistoryService, root: Path
):
    service.create_environment("work", root, ["a", "missing"], select=True)
    (root / "unselected").write_bytes(b"not selected")
    snap = service.snapshot()
    assert [entry.path for entry in snap.entries] == ["a", "missing"]
    assert [entry.status for entry in service.diff_live(snap.id).entries] == [
        "unchanged",
        "unchanged",
    ]
    assert len(snap.entries) == 2


def test_corrupt_saved_environment_paths_rejected_before_capture(
    service: HistoryService, root: Path
):
    service.create_environment("work", root, ["a"], select=True)
    env_path = service.store.root / "environments/work.toml"
    env_path.write_text(env_path.read_text().replace('"a"', '"../outside"'))
    with pytest.raises(HistoryError) as exc:
        service.snapshot()
    assert exc.value.code == "invalid_path"


def test_store_subdirectory_symlink_rejected_without_writing_outside(tmp_path: Path):
    state = tmp_path / "state"
    state.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (state / "objects").symlink_to(outside, target_is_directory=True)
    with pytest.raises(HistoryError) as exc:
        HistoryService(state).create_environment("empty")
    assert exc.value.code == "symlink"
    assert list(outside.iterdir()) == []


def test_atomic_record_write_rejects_unchecked_paths(service: HistoryService):
    with service.store.lock(), pytest.raises(HistoryError) as exc:
        service.store.atomic_json("../escape.json", {"schema_version": 1})
    assert exc.value.code == "invalid_path"


def test_no_default_environment_is_a_missing_choice(service: HistoryService):
    with pytest.raises(HistoryError) as exc:
        service.get_environment()
    assert exc.value.exit_code == 3
    assert exc.value.code == "no_environment_selected"


def test_corrupt_run_json_has_content_free_error(service: HistoryService):
    with service.store.lock():
        run, _ = service.store.begin_run("snapshot", {"environment": "work"})
        with service.store.connection() as conn:
            conn.execute(
                "UPDATE runs SET arguments=? WHERE id=?", ("secret malformed data", run.id)
            )
        with pytest.raises(HistoryError) as exc:
            service.store.get_run(run.id)
    assert exc.value.code == "invalid_record"
    assert "secret" not in str(exc.value)


@pytest.mark.parametrize(
    ("root_name", "file_name"),
    [("root😀", "a"), ("root", "a😀"), ("root", "a\x7f"), ("root", 'a"\t\né')],
)
def test_environment_toml_round_trips_unicode_and_controls(
    service: HistoryService, tmp_path: Path, root_name: str, file_name: str
):
    root = tmp_path / root_name
    root.mkdir()
    (root / file_name).write_bytes(b"preserved")
    environment = service.create_environment("unicode", root, [file_name], select=True)
    reopened = HistoryService(service.store.root)
    assert reopened.get_environment() == environment
    snapshot = reopened.snapshot()
    assert snapshot.root == str(root)
    assert snapshot.entries[0].path == file_name
    assert reopened.store.read_object(snapshot.entries[0].state.sha256) == b"preserved"


@pytest.mark.parametrize("existing_state", [False, True])
def test_state_ancestor_symlink_rejected_before_creation_or_chmod(
    tmp_path: Path, existing_state: bool
):
    outside = tmp_path / "outside"
    outside.mkdir()
    state = outside / "state"
    if existing_state:
        state.mkdir(mode=0o755)
        (state / "objects").mkdir(mode=0o755)
    previous_modes = {path.relative_to(outside): path.stat().st_mode for path in outside.rglob("*")}
    (tmp_path / "alias").symlink_to(outside, target_is_directory=True)
    with pytest.raises(HistoryError) as exc:
        HistoryService(tmp_path / "alias/state").create_environment("empty")
    assert exc.value.code == "symlink"
    assert {
        path.relative_to(outside): path.stat().st_mode for path in outside.rglob("*")
    } == previous_modes

import os
from pathlib import Path

import pytest

from permaenv.errors import HistoryError
from permaenv.files import ConfinedFiles, FileState, validate_relative_path


@pytest.mark.parametrize(
    "path",
    [
        "",
        "/etc/passwd",
        "../x",
        "a/../x",
        "./a",
        "a//b",
        ".vscode/settings.json",
        "x/.idea/a",
        ".mcp.json",
        "a\\b",
    ],
)
def test_unsafe_paths_rejected(path: str) -> None:
    with pytest.raises(HistoryError, match=r"relative|configuration"):
        validate_relative_path(path)


def test_atomic_mutations_preserve_modes_and_require_expected_state(tmp_path: Path) -> None:
    (tmp_path / "nested").mkdir()
    with ConfinedFiles(tmp_path) as files:
        missing = files.read("nested/x")
        assert missing.state == FileState.absent()
        files.write("nested/x", b"one", 0o640, expected=missing.state)
        original = files.read("nested/x")
        assert original.data == b"one"
        assert original.state.mode == 0o640
        with pytest.raises(HistoryError) as exc:
            files.write("nested/x", b"two", 0o600, expected=missing.state)
        assert exc.value.code == "stale_state"
        assert files.read("nested/x").data == b"one"
        files.delete("nested/x", expected=original.state)
        assert files.read("nested/x").state == FileState.absent()


def test_symlinks_special_files_and_missing_parents_are_distinct(tmp_path: Path) -> None:
    (tmp_path / "real").mkdir()
    (tmp_path / "leaf").symlink_to("real")
    (tmp_path / "parent").symlink_to("real", target_is_directory=True)
    os.mkfifo(tmp_path / "pipe")
    with ConfinedFiles(tmp_path) as files:
        for path, code in [
            ("leaf", "symlink"),
            ("parent/x", "symlink"),
            ("pipe", "special_file"),
            ("missing/x", "missing_parent"),
        ]:
            with pytest.raises(HistoryError) as exc:
                files.read(path)
            assert exc.value.code == code


def test_unreadable_capture_fails_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / "x").write_bytes(b"data")

    def denied(*args: object) -> bytes:
        raise PermissionError("no")

    monkeypatch.setattr(os, "read", denied)
    with ConfinedFiles(tmp_path) as files, pytest.raises(HistoryError) as exc:
        files.read("x")
    assert exc.value.code == "inaccessible"


def test_changing_capture_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "x"
    target.write_bytes(b"before")
    real_read = os.read

    def changing(fd: int, size: int) -> bytes:
        result = real_read(fd, size)
        if result:
            target.write_bytes(b"after")
        return result

    monkeypatch.setattr(os, "read", changing)
    with ConfinedFiles(tmp_path) as files, pytest.raises(HistoryError) as exc:
        files.read("x")
    assert exc.value.code == "unstable_file"


def test_root_ancestor_symlink_is_not_followed(tmp_path: Path):
    (tmp_path / "real").mkdir()
    (tmp_path / "real/root").mkdir()
    (tmp_path / "alias").symlink_to("real", target_is_directory=True)
    with pytest.raises(HistoryError) as exc, ConfinedFiles(tmp_path / "alias/root"):
        pass
    assert exc.value.code == "symlink"


def test_parent_moved_outside_root_before_replace_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root = tmp_path / "root"
    root.mkdir()
    (root / "nested").mkdir()
    (root / "nested/x").write_bytes(b"original")
    fsync = os.fsync
    moved = False

    def move_parent(fd: int):
        nonlocal moved
        fsync(fd)
        if not moved:
            moved = True
            (root / "nested").rename(tmp_path / "outside")
            (root / "nested").mkdir()
            (root / "nested/x").write_bytes(b"original")

    with ConfinedFiles(root) as files:
        before = files.read("nested/x").state
        monkeypatch.setattr(os, "fsync", move_parent)
        with pytest.raises(HistoryError) as exc:
            files.write("nested/x", b"replacement", 0o600, expected=before)
    assert exc.value.code == "stale_state"
    assert (tmp_path / "outside/x").read_bytes() == b"original"

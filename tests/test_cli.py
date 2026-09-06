"""Exercise the real CLI with a controlled HOME and PATH."""

import json
import os
import subprocess
import sys
from pathlib import Path


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"HOME": str(tmp_path), "PATH": str(tmp_path / "bin"), "NO_COLOR": "1"}
    return subprocess.run(
        [sys.executable, "-m", "permaenv", *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
        check=False,
    )


def test_doctor_emits_json_when_optional_tools_are_missing(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "doctor", "--json")
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_version"] == 1
    assert report["platform"]["os"] in {"macos", "linux"}
    assert report["platform"]["supported"] is True
    assert report["tools"]
    assert all(tool["path"] is None for tool in report["tools"])
    assert result.stderr == ""


def test_doctor_finds_executable_without_running_it_or_writing_settings(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    marker = tmp_path / "executed"
    executable = bin_dir / "git"
    executable.write_text(f'#!/bin/sh\nprintf executed > "{marker}"\n')
    executable.chmod(0o755)
    result = run_cli(tmp_path, "doctor", "--json")
    assert result.returncode == 0, result.stderr
    tools = {item["name"]: item for item in json.loads(result.stdout)["tools"]}
    assert tools["git"]["path"] == str(executable)
    assert tools["npm"]["path"] is None
    assert not marker.exists()
    assert list(tmp_path.iterdir()) == [bin_dir]


def test_doctor_ignores_non_executable_file(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text("not executable\n")
    result = run_cli(tmp_path, "doctor", "--json")
    assert result.returncode == 0, result.stderr
    tools = {item["name"]: item for item in json.loads(result.stdout)["tools"]}
    assert tools["git"]["path"] is None


def test_doctor_produces_human_readable_report(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "doctor")
    assert result.returncode == 0, result.stderr
    assert "PermaEnv" in result.stdout
    assert "git" in result.stdout
    assert "Not on PATH" in result.stdout


def test_help_lists_only_available_commands(tmp_path: Path) -> None:
    result = run_cli(tmp_path, "--help")
    assert result.returncode == 0, result.stderr
    assert "doctor" in result.stdout
    unknown = run_cli(tmp_path, "backup")
    assert unknown.returncode == 2

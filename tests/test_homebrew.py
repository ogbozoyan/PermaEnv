"""Exercise the release artifact generator through its command-line interface."""

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "generate_homebrew_formula.py"


def run_generator(tmp_path: Path, extra: str = "") -> subprocess.CompletedProcess[str]:
    archive = tmp_path / "permaenv-1.2.3.tar.gz"
    archive.write_bytes(b"synthetic source archive")
    (tmp_path / "uv.lock").write_text(
        """version = 1
[[package]]
name = "permaenv"
version = "1.2.3"
dependencies = [{name = "example"}, {name = "windows-only", marker = "sys_platform == 'win32'"}]
[[package]]
name = "example"
version = "2.0"
sdist = {url = "https://files.pythonhosted.org/example-2.0.tar.gz", hash = "sha256:"""
        + "a" * 64
        + """"}
"""
        + extra
    )
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--sdist", str(archive), "--lock", str(tmp_path / "uv.lock")],
        capture_output=True,
        text=True,
        check=False,
    )


def test_formula_has_source_checksum_and_only_runtime_resources(tmp_path: Path) -> None:
    result = run_generator(tmp_path)
    assert result.returncode == 0, result.stderr
    formula = result.stdout
    assert "releases/download/v1.2.3/permaenv-1.2.3.tar.gz" in formula
    assert hashlib.sha256(b"synthetic source archive").hexdigest() in formula
    assert 'resource "example"' in formula
    assert "windows-only" not in formula
    assert 'depends_on "python@3.12"' in formula
    assert "virtualenv_install_with_resources" in formula
    assert "doctor --json" in formula


@pytest.mark.parametrize(
    "extra",
    [
        # Resolving ambiguous package versions needs an explicit policy, never first-match wins.
        '[[package]]\nname = "example"\nversion = "3.0"\n',
        # A new dependency cannot quietly disappear from the formula.
        'dependencies = [{name = "missing"}]\n',
        # One portable formula cannot silently use a different graph on Linux and macOS.
        'dependencies = [{name = "mac-only", marker = "sys_platform == \'darwin\'"}]\n',
    ],
)
def test_unsupported_dependency_graph_fails_without_partial_formula(
    tmp_path: Path, extra: str
) -> None:
    result = run_generator(tmp_path, extra)
    assert result.returncode != 0
    assert result.stdout == ""


def test_archive_version_must_match_lock(tmp_path: Path) -> None:
    run_generator(tmp_path)
    archive = tmp_path / "permaenv-9.9.9.tar.gz"
    archive.write_bytes(b"wrong release")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--sdist", str(archive), "--lock", str(tmp_path / "uv.lock")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert result.stdout == ""

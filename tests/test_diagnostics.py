"""Platform handling must not classify every operating system as supported."""

import pytest


@pytest.mark.parametrize(
    ("system", "expected_os", "supported"),
    [("Darwin", "macos", True), ("Linux", "linux", True), ("Windows", "windows", False)],
)
def test_platform_support(
    monkeypatch: pytest.MonkeyPatch, system: str, expected_os: str, supported: bool
) -> None:
    from permaenv import diagnostics

    monkeypatch.setattr(diagnostics.platform, "system", lambda: system)
    report = diagnostics.inspect_environment()
    assert report.platform.os == expected_os
    assert report.platform.supported is supported


def test_unsupported_platform_has_nonzero_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from typer.testing import CliRunner

    from permaenv import diagnostics
    from permaenv.cli import app

    monkeypatch.setattr(diagnostics.platform, "system", lambda: "Windows")
    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["platform"]["supported"] is False

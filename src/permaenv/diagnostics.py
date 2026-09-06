"""Read-only executable discovery. No application is launched or configured."""

import platform
import shutil
from dataclasses import dataclass

TOOLS = ("git", "brew", "npm", "node", "uv", "zsh", "code", "idea", "codex", "claude")


@dataclass(frozen=True, slots=True)
class PlatformInfo:
    os: str
    architecture: str
    python: str
    supported: bool


@dataclass(frozen=True, slots=True)
class ToolInfo:
    name: str
    path: str | None


@dataclass(frozen=True, slots=True)
class EnvironmentReport:
    schema_version: int
    platform: PlatformInfo
    tools: tuple[ToolInfo, ...]


def inspect_environment() -> EnvironmentReport:
    """Check platform and PATH without executing tools or reading their settings."""
    system = platform.system()
    return EnvironmentReport(
        schema_version=1,
        platform=PlatformInfo(
            os={"Darwin": "macos", "Linux": "linux"}.get(system, system.lower()),
            architecture=platform.machine(),
            python=platform.python_version(),
            supported=system in {"Darwin", "Linux"},
        ),
        tools=tuple(ToolInfo(name=name, path=shutil.which(name)) for name in TOOLS),
    )

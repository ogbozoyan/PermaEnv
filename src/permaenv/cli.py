"""Command-line presentation; environment inspection lives outside this module."""

import json
from dataclasses import asdict
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from permaenv import __version__
from permaenv.diagnostics import inspect_environment

app = typer.Typer(
    name="permaenv",
    help="A portable home for your developer environment.",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
)


@app.callback()
def main() -> None:
    """Inspect your environment with PermaEnv."""


@app.command()
def doctor(
    json_output: Annotated[
        bool, typer.Option("--json", help="Emit a versioned JSON report.")
    ] = False,
) -> None:
    """Check the platform and optional tools on PATH without modifying your machine."""
    report = inspect_environment()
    if json_output:
        typer.echo(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    else:
        console = Console()
        console.print(Text(f"PermaEnv {__version__}", style="bold cyan"))
        console.print(
            Text(
                f"{report.platform.os} · {report.platform.architecture} · "
                f"Python {report.platform.python}"
            )
        )
        table = Table("Tool", "Executable on PATH", box=None, padding=(0, 2))
        for tool in report.tools:
            path = Text(tool.path) if tool.path else Text("Not on PATH", style="dim")
            table.add_row(tool.name, path)
        console.print(table)
        console.print("Read-only check. No tools were executed or settings changed.", style="dim")
        if not report.platform.supported:
            console.print("This platform is not supported; use macOS or Linux.", style="yellow")
    if not report.platform.supported:
        raise typer.Exit(1)

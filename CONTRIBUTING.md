# Contributing to PermaEnv

PermaEnv is at the CLI-foundation stage. Please keep pull requests focused on working,
testable behavior. Discuss a new subsystem in an issue before implementing it.

## Local setup

1. Fork and clone the repository.
2. Install [uv](https://docs.astral.sh/uv/getting-started/installation/).
3. Run `uv sync --locked`.
4. Create a branch for your change.

Before opening a pull request, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build
uv run twine check dist/*
```

## Code and tests

- Keep the Python core independent of terminal rendering and future desktop interfaces.
- Add behavior tests for fixes and new functionality. Use temporary directories and
  synthetic configuration files, never your actual settings or credentials.
- Preserve machine-readable output contracts; explain a deliberate format change.
- Do not run discovered tools just to prove that they exist.
- Add dependencies only when the implemented feature needs them. Update `uv.lock` with `uv lock`.

## Pull requests

Describe the problem, the resulting behavior and the checks you ran. Include the OS
and Python version when platform behavior is relevant. Keep the README accurate about
what users can run today.

This repository contains implementation, tests, distributable artifacts and user-facing
documentation. Internal planning notes, design specifications and agent transcripts stay
outside the public repository and its Git history.

## Reporting issues

Use the issue templates. Remove usernames or private paths where appropriate and never
attach tokens, `.env` files, authentication databases or real backups. Report security
issues privately using the process in [SECURITY.md](SECURITY.md).

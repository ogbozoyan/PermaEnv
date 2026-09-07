<div align="center">

<img src="https://raw.githubusercontent.com/ogbozoyan/PermaEnv/main/assets/banner.png" alt="PermaEnv — Your developer setup, saved for what’s next. An archive of saved snapshots in warm terracotta and amber." width="1200" />

**A simpler way to save, version, and move your developer setup.**

[![CI](https://github.com/ogbozoyan/PermaEnv/actions/workflows/ci.yml/badge.svg)](https://github.com/ogbozoyan/PermaEnv/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.12%2B-8B5E46?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-BB6548)](LICENSE)
![Status: pre-alpha](https://img.shields.io/badge/status-pre--alpha-C99548)

[Get started](#get-started) · [Current status](#current-status) · [Contribute](CONTRIBUTING.md) · [Report an issue](https://github.com/ogbozoyan/PermaEnv/issues/new/choose)

</div>

---

Setting up a new machine should not mean reconstructing years of small decisions.
Your shell, editor extensions, language runtimes and AI tools are part of how you work.
PermaEnv is being built to give that environment a history—and a way home.

```text
                      P E R M A E N V

        Discover  →  Snapshot  →  Compare  →  Restore
                         │
                         └── Back up to
                             Local · Git · Google Drive
```

*The flow above describes the product direction. This repository currently ships the CLI foundation.*

## Current status

**Pre-alpha.** Available today:

- An installable Python package and `permaenv` command.
- `permaenv doctor`: a read-only check of the platform and selected executables on `PATH`.
- Human-readable output and a versioned JSON report for scripts.
- Tests, linting, type checks and package builds in GitHub Actions on macOS and Linux.

Snapshots, backups, restoration, application adapters, MCP and the interactive menu
are **not implemented yet**. Do not rely on this version to protect or recover your settings.

## Get started

**Install the current development version, or build it yourself.** Both paths work on
macOS and Linux. The CLI requires Python 3.12+; uv can install that interpreter for you.

| Your goal | Start here |
| :--- | :--- |
| Use PermaEnv on your machine | [Install with your package manager](#install-with-your-package-manager) |
| Run or change the source | [Build locally](#build-locally) |
| Install a native Homebrew release | [Homebrew release status](#homebrew-release-status) |

### Install with your package manager

Use your system's manager to install the tooling below, then install PermaEnv from
its Git repository into an isolated environment. These commands track `main`.

<details open>
<summary><strong>macOS · Homebrew + uv</strong></summary>

```bash
brew install git uv
uv tool install --python 3.12 "git+https://github.com/ogbozoyan/PermaEnv.git@main"
uv tool update-shell
```

Open a new terminal after updating your PATH, then run `permaenv doctor`.
Already have Git and uv on Linux? The same `uv tool install` command works there.

</details>

<details>
<summary><strong>Linux · APT, DNF or Pacman + pipx</strong></summary>

Install Git, Python and pipx using the command for your distribution:

| Distribution | Prepare the tools |
| :--- | :--- |
| Ubuntu 24.04+ / Debian 13+ | `sudo apt update` then `sudo apt install git python3 python3-venv pipx` |
| Fedora with Python 3.12+ | `sudo dnf install git python3 pipx` |
| Arch Linux | `sudo pacman -Syu --needed git python python-pipx` |

Then install the application:

```bash
python3 --version
pipx install --python python3 "git+https://github.com/ogbozoyan/PermaEnv.git@main"
pipx ensurepath
```

The reported Python version must be 3.12 or newer. On older distributions, use
[uv](https://docs.astral.sh/uv/getting-started/installation/) and the `--python 3.12`
installation command above. Open a new terminal after `pipx ensurepath`, then run
`permaenv doctor`.

APT, DNF and Pacman install the prerequisites here; PermaEnv itself is fetched from
Git. Native PermaEnv packages for these managers have not been published.

</details>

<details>
<summary><strong>macOS · MacPorts + uv</strong></summary>

```bash
sudo port install git uv
uv tool install --python 3.12 "git+https://github.com/ogbozoyan/PermaEnv.git@main"
uv tool update-shell
```

Open a new terminal, then run `permaenv doctor`. MacPorts supplies the tooling;
there is no native PermaEnv port yet.

</details>

Refresh the development installation with the tool you used to install it:

```bash
uv tool upgrade permaenv       # uv installation
pipx reinstall permaenv        # Fetch main again, even if the package version is unchanged
```

See the official [uv tool guide](https://docs.astral.sh/uv/guides/tools/) and
[pipx installation guide](https://pipx.pypa.io/latest/how-to/install-pipx.html)
for PATH setup and platform prerequisites.

### Build locally

You need Git and [uv](https://docs.astral.sh/uv/getting-started/installation/).
Clone the source, install the locked development environment and run the CLI:

```bash
git clone https://github.com/ogbozoyan/PermaEnv.git
cd PermaEnv
uv sync --locked
uv run permaenv doctor
```

Build the wheel and source archive, then install your local wheel as a command:

```bash
uv build
uv tool install --python 3.12 dist/permaenv-*.whl
```

The build writes `.whl` and `.tar.gz` files to `dist/`. Keep only one version's wheel
there when using the wildcard above. If PermaEnv is already installed through uv,
add `--force` to replace that installation with your local build. Use
`uv tool update-shell` and reopen the terminal if the command is not on PATH.

### Homebrew release status

**Coming after the first release.** CI already generates a checksummed Homebrew formula,
but the release and tap have not been published. The intended native install is:

```bash
# Available after the first release and tap are published.
brew install ogbozoyan/tap/permaenv
brew upgrade permaenv
```

The formula will manage Python and PermaEnv's dependencies. The future macOS desktop
app will have a separate cask. Until then, use the source installation or local build above.

## Check your setup

```bash
permaenv --help
permaenv doctor
permaenv doctor --json
```

It reports the operating system, architecture, Python version and the paths of tools
such as Git, Homebrew, npm, Node.js, uv, Zsh, VS Code, IntelliJ IDEA, Codex and Claude.

**It only checks executable availability on `PATH`.** It does not run these tools,
read their configuration files, scan your home directory or send data anywhere.
A missing command is reported as **Not on PATH**; it does not prove the application
is uninstalled. Optional tools do not cause a failed check. An unsupported operating
system returns exit code `1`.

JSON output goes to stdout without terminal formatting. The report includes
`schema_version`, `platform` and `tools`; command paths can contain your username,
so review output before sharing it in a public issue.

## Where PermaEnv is headed

| Area | Planned experience |
| :--- | :--- |
| Environment history | Select what matters, capture a snapshot and inspect changes |
| Backups | Choose a local directory, Git repository or Google Drive folder |
| Recovery | Review a restore plan, resolve conflicts and preserve files before changes |
| Editors & shells | User settings and plugins for VS Code, JetBrains IDEs and Zsh |
| Packages & runtimes | Track package sources, installed versions and separate installations |
| AI tools | Carry supported MCP configurations, instructions and skills between machines |
| Extensibility | Add simple apps with recipes and complex integrations with adapters |
| Interfaces | CLI and terminal UI first; MCP and a desktop companion follow |

Project-local configuration is outside the initial scope. Secrets, caches and chat
history will require explicit handling rather than copying entire application folders.

## Built with

The current CLI uses **Python, Typer and Rich**, packaged with **Hatchling** and managed
with **uv**. Development checks use **pytest, Ruff and mypy**.

The next components will use **Textual** for the terminal UI, the official **Python MCP SDK**,
and **SQLite** for local metadata. The future desktop stays on **Tauri 2 + React + TypeScript + Vite**,
with a Python core running as a managed local process. The application logic stays in Python.

## Development

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build
uv run twine check dist/*
```

CI runs the tests on Python 3.12, 3.13 and 3.14 across macOS and Linux. It also builds
the wheel and source distribution, installs the wheel into a separate environment,
and uploads both distributions plus a generated Homebrew formula as workflow artifacts.
A manual **Build artifacts** workflow produces the same artifacts. Pushing a `v<version>`
tag matching `pyproject.toml` prepares a **draft GitHub release** with those files.
No package registry or tap is updated automatically.

To prepare the Homebrew artifact locally after `uv build`:

```bash
uv run python scripts/generate_homebrew_formula.py --sdist dist/*.tar.gz > dist/permaenv.rb
ruby -c dist/permaenv.rb
```

For a release, publish the draft with its original source archive, then add the generated
formula to `Formula/permaenv.rb` in the planned `ogbozoyan/homebrew-tap` repository.
The formula's source URL becomes usable only after that release is published. Test the
tap with `brew install --build-from-source ogbozoyan/tap/permaenv` and
`brew test ogbozoyan/tap/permaenv` on macOS and Linux before announcing availability.
The generator refuses dependency graphs it cannot represent safely in one formula;
extend it and its tests when adding platform-specific runtime dependencies.

## Contributing

Small, focused contributions are welcome: reproducible bug reports, platform fixes,
tests and improvements to the CLI foundation. For a new integration, open an issue
describing the application, its configuration locations and the state worth preserving.

Start with [CONTRIBUTING.md](CONTRIBUTING.md). Never include credentials, real environment
backups or private application data in a pull request.

## License

[MIT](LICENSE) © 2026 ogbozoyan and contributors.

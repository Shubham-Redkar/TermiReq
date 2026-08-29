# STDLIB.md

In accordance with the Zero-Dependency Hackathon rules (Track B), this project relies entirely on Python's Standard Library. Here are the substitutions we made and why:

| Normally you'd install | Instead we used | Rationale |
|---|---|---|
| A terminal emulation library (e.g., `pyte`) | Hand-rolled `parser.py` + `screen.py` | Building the parser and virtual screen model from scratch *is* the core objective of Track B. |
| `python-Levenshtein` / diff libraries for text | Custom cell-grid diff in `diff.py` | Terminal diffing requires cursor/scroll awareness that a generic text diff library lacks. |
| `pexpect` (pty automation) | `pty` (stdlib) + `subprocess` | We used the built-in `pty` module to spawn a real pseudo-terminal without a wrapper library. |
| `click` / `typer` | `argparse` | `argparse` is more than capable for our CLI surface and avoids a third-party dependency. |
| `colorama` (cross-platform ANSI) | Raw ANSI escapes, `NO_COLOR` check | Output styling and parsing is handled internally by decoding raw ANSI escape sequences directly. |
| `sh` / `plumbum` (shell command chaining) | `subprocess` + `pty` directly | Sequential command execution is handled manually via the standard library to maintain zero dependencies. |

*Note: This list will be expanded as we hit further architectural decisions during implementation.*

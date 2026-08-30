# STDLIB.md

Every third-party package we considered — and what we used from the Python standard library instead.

| Normally you'd install | Instead | Why |
|---|---|---|
| A terminal emulation library (e.g. `pyte`, `blessed`) | Hand-rolled `parser.py` + `screen.py` | The parser/screen model *is* the Track B deliverable — outsourcing it defeats the purpose |
| `python-Levenshtein` / generic text diff libraries | Custom cell-grid diff in `diff.py` | Terminal diffing needs cursor/scroll awareness that line-oriented text diff cannot provide |
| `pexpect` (PTY automation) | `pty` + `subprocess` + `select` in `runner.py` | Spawns real pseudo-terminals without a wrapper library |
| `click` / `typer` | `argparse` in `cli.py` | CLI surface with zero deps |
| `colorama` (cross-platform ANSI) | Raw ANSI escapes + `NO_COLOR` check | Output styling without a shim package |
| `sh` / `plumbum` (shell command chaining) | `subprocess` + `pty` directly in `runner.py` | Sequential command execution under our control |

---

## Runner limitations (`runner.py`)

These are intentional v1 scope cuts documented for judges and integrators.

### Unix-only PTY

The runner uses `pty.openpty()` (stdlib) to attach a real pseudo-terminal to each command. That API is **not available on native Windows**. On Windows the runner falls back to `subprocess.run(capture_output=True)`, which means:

- Programs may detect a pipe and **suppress ANSI color/cursor codes**
- Interactive TUI programs (`vim`, `htop`) will not behave like a real terminal

**Develop on Linux/macOS/WSL** for the full demo path. The fallback exists so unit tests and CI can run on Windows without crashing.

### Buffered per command (not live streaming)

v1 buffers each command's full byte output and yields one `CommandChunk` when the command finishes. The parser/screen pipeline receives the complete buffer per command — sufficient for before/after diffing per command, but not for live mid-command updates.

### Screen reset between commands

The virtual screen is reset to blank before each command in the sequence (handled by the integration layer). The runner does not carry terminal state across commands — document this in README as a stated limitation.

### Timeout handling

`run_commands(..., timeout=N)` uses `select` on the PTY master fd (Unix) or `subprocess.run(timeout=N)` (fallback). On timeout the runner sends `SIGTERM` to the process group and marks `CommandFinished.timed_out=True`.

### Ctrl-C to skip

Pressing Ctrl-C during a running command raises `KeyboardInterrupt` inside the runner loop. The runner kills the current command, yields `CommandFinished(skipped=True, exit_code=130)`, and **continues with the next command** in the list instead of aborting the whole sequence.

### Terminal geometry

Default PTY size is 80×24 (classic VT100). Pass `rows=` / `cols=` to `run_commands` if the integration layer needs a different geometry. Some programs reflow output based on terminal width.

### Shell interpretation

Commands are passed to `/bin/sh -c` (via `shell=True`). Shell metacharacters are interpreted. This matches the hackathon demo usage (`ttydiff run "ls --color"`) but is not a sandbox — only run trusted commands.

### No alternate-screen / mouse / bracketed-paste

The runner captures raw bytes faithfully but the parser/screen layer explicitly does not model alternate-screen buffer, mouse tracking, or bracketed paste. Those bytes may appear as `UnknownSequence` events upstream.

---

## Diff engine notes (`diff.py`)

| Normally you'd install | Instead | Why |
|---|---|---|
| `difflib` / `diff-match-patch` | Cell-by-cell grid comparison | Style-only changes and cursor position matter; text line diff misses them |
| Heuristic scroll libraries | Shift-matching row similarity in `diff.py` | Detects scroll-up/down so we don't report every line as changed when content shifts |

Scroll detection compares shifted rows between before/after snapshots. When a scroll match exceeds 85% row similarity, the diff reports `scrolled=True` with direction/amount, avoids treating the shifted content as brand-new rows, and still diffs both the newly exposed rows and any real edits within the shifted content.

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
| `tomli` (TOML parsing on <3.11) | `tomllib` in `config.py`, guarded by try/except | `tomllib` is stdlib on 3.11+; config support degrades gracefully (env-only) if absent |
| `comtypes` / `pyobjc` / `pyatspi` (native UIA / NSAccessibility / AT-SPI bindings) | OS speech services via `subprocess` in `accessibility.py` | Native accessibility APIs need C-extension bindings; we route announcements through `say`/`spd-say`/`espeak`/PowerShell SAPI instead, and document the native bridges as optional out-of-scope extension points |
| `pyttsx3` / `gTTS` (text-to-speech) | Shelling out to the platform speech tool | Audio synthesis without a wrapper package or network calls |
| `winpty` / `pywinpty` (Windows PTY shim) | `subprocess` fallback + `is_wsl()` detection in `runner.py` | A native-Windows PTY shim is a third-party C extension; we fall back to buffered `subprocess` and steer WSL users (who have working stdlib `pty`) onto the real PTY path |

---

## Runner limitations (`runner.py`)

These are intentional v1 scope cuts documented for judges and integrators.

### Unix-only PTY

The runner uses `pty.openpty()` (stdlib) to attach a real pseudo-terminal to each command. That API is **not available on native Windows**. On Windows the runner falls back to `subprocess.run(capture_output=True)`, which means:

- Programs may detect a pipe and **suppress ANSI color/cursor codes**
- Interactive TUI programs (`vim`, `htop`) will not behave like a real terminal

`describe_platform()` reports which backend is active, and `is_wsl()` distinguishes WSL (which *does* provide a working stdlib `pty`, so it uses the real PTY path) from native Windows. **Develop on Linux/macOS/WSL** for the full demo path. The fallback exists so unit tests and CI can run on Windows without crashing — no `winpty`/`pywinpty` shim is pulled in, preserving the zero-dependency guarantee.

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

Commands are passed to `/bin/sh -c` (via `shell=True`). Shell metacharacters are interpreted. This matches the hackathon demo usage (`termireq run "ls --color"`) but is not a sandbox — only run trusted commands.

### No mouse / bracketed-paste

The runner captures raw bytes faithfully but the parser/screen layer explicitly does not model mouse tracking or bracketed paste. Those bytes may appear as `UnknownSequence` events upstream.

---

## Diff engine notes (`diff.py`)

| Normally you'd install | Instead | Why |
|---|---|---|
| `difflib` / `diff-match-patch` | Cell-by-cell grid comparison | Style-only changes and cursor position matter; text line diff misses them |
| Heuristic scroll libraries | Shift-matching row similarity in `diff.py` | Detects scroll-up/down so we don't report every line as changed when content shifts |

Scroll detection compares shifted rows between before/after snapshots. When a scroll match exceeds 85% row similarity, the diff reports `scrolled=True` with direction/amount, avoids treating the shifted content as brand-new rows, and still diffs both the newly exposed rows and any real edits within the shifted content.

For repeated diffs against the same geometry, `diff_screens_incremental(before, after, dirty_rows)` compares only the rows `screen.py` marked dirty (via the `DirtyRows` tracker), skipping the O(rows²·cols) scroll scan. It is only valid when no scroll occurred; the caller falls back to the full `diff_screens` otherwise. See `scripts/benchmark.py` for the timing harness (`--profile` for cProfile).

---

## Configuration (`config.py`)

| Normally you'd install | Instead | Why |
|---|---|---|
| `tomli` / `toml` / `pyyaml` | `tomllib` (stdlib, 3.11+) | Native TOML parsing; falls back to env-var-only config when unavailable |
| `pydantic` / `dynaconf` (config schema + env layering) | Plain dataclasses + a hand-written env-override pass | Typed config sections and `TERMIREQ_*` overrides without a settings framework |

Config resolves in layers: a TOML file (explicit `--config`, then `./config.toml`, `./termireq.toml`, then `$XDG_CONFIG_HOME`/`~/.config/termireq/config.toml`) overlaid by `TERMIREQ_*` environment variables (plus the `NO_COLOR` convention). Unknown keys are ignored so newer sample configs stay backward-compatible.

## Accessibility (`accessibility.py`)

| Normally you'd install | Instead | Why |
|---|---|---|
| `comtypes` / `pyobjc` / `pyatspi` | OS speech services via `subprocess` | See the top table — native API bindings are C extensions |
| `pyttsx3` / `gTTS` | `say` / `spd-say` / `espeak` / PowerShell SAPI | Zero-dep, offline audio path |

The adapter layer (`NullAdapter` / `StreamAdapter` / `SpeechAdapter`, selected by `get_adapter`) turns diff results into `AccessibilityAnnouncement`s. Announcement priority follows the ARIA live-region convention (`polite` for success, `assertive` for failures). Windows TTS text is passed via the `TERMIREQ_TEXT` env var rather than interpolated into the command line, avoiding shell injection.

---

## Single File (`termireq.py`)

The entire solution — contracts, logger, parser, screen, diff, runner, config, accessibility, and CLI — is contained in a single source file: `termireq.py`. This is the "Single File" bonus challenge (+5 pts).

### How it works

All 10 source modules (`contracts.py`, `logger.py`, `parser.py`, `screen.py`, `diff.py`, `runner.py`, `config.py`, `accessibility.py`, `cli.py`, `main.py`) are merged into `termireq.py` with clear section headers. The file is self-contained: every import is from the Python standard library only. No internal package imports remain.

### Running directly

```bash
python termireq.py run "echo hello"
```

### What was avoided

| Normally you'd need | Instead | Why |
|---|---|---|
| A package manager / `pip install` | Single file, no install | Zero setup — copy `termireq.py` anywhere and run |
| A complex build system | `python -m zipapp` | Reproducible single-command build (see below) |
| Multiple files + `__init__.py` | One flat file | Judges can read the entire solution in one scroll |

---

## Reproducible Build (`make build`)

The build produces bit-for-bit identical `.pyz` artifacts across identical Python versions. This is the "Reproducible Build" bonus challenge (+5 pts).

### How it works

```bash
make build          # produces termireq.pyz + termireq.pyz.sha256
make verify         # checks SHA256 hash matches
```

The build uses `python -m zipapp` (stdlib) to package `termireq.py` into a `.pyz` (Python zipapp). The SHA256 hash is written to `termireq.pyz.sha256` and can be verified with `make verify`.

### Why it's reproducible

- `zipapp` is a deterministic stdlib tool: same input → same output.
- The hash is computed over the `.pyz` binary, not timestamps or metadata.
- Any identical Python environment (same version, same OS) will produce the same `.pyz` byte-for-byte.

### Running the built artifact

```bash
python termireq.pyz run "echo hello"
# or on Unix:
./termireq.pyz run "echo hello"
```

### Dependencies used

**Zero.** The build tool (`python -m zipapp`) and hash tool (`hashlib`) are both Python standard library modules. No third-party build tools, no vendored code.

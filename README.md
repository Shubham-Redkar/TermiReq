# TermiReq (tyydiff)

**TermiReq** (also known as `tyydiff`) is a semantic diffing engine for terminal screens built entirely using Python's standard library. 

It reads the raw byte stream a terminal program emits (including ANSI/VT100 escape sequences), maintains a virtual screen model, and reports **only what changed** between frames. This provides the foundational layer that a real screen reader or terminal-monitoring tool would sit on top of.

## Features

- **ANSI/VT100 Parsing:** Decodes hidden terminal codes.
- **Virtual Screen:** Builds a 2D model of what is on the screen at any moment.
- **Semantic Diffing:** Compares two moments in time and reports only structural changes (including character and style changes).
- **Sequential Command Runner:** Feed it a list of shell commands, and it runs them one after another through a real pseudo-terminal (PTY) so programs emit full formatting, printing a diff summary after each.
- **Colorized Diff Output:** Human-readable diffs are colorized (honoring `NO_COLOR` and tty detection); `--no-color` or config disables it.
- **Accessibility Announcements:** Turns each diff into spoken/streamed announcements through the OS speech service (`say`/`spd-say`/`espeak`/PowerShell SAPI) — no third-party TTS package.
- **Configuration File:** Optional `config.toml` (terminal geometry, color, accessibility) with `TTYDIFF_*` environment overrides.
- **Cross-Platform:** Real PTY on Linux/macOS/WSL, buffered `subprocess` fallback on native Windows; CI runs the suite on all three across Python 3.11–3.13.

## Usage

```bash
# Run multiple commands sequentially and diff their output
python -m src.main run "ls -la" "htop" "git status"
```

```bash
# Disable color, or emit accessibility announcements
python -m src.main run "ls -la" --no-color
python -m src.main run "make" --accessibility            # auto-selects a backend
python -m src.main run "make" --speak                    # read the diff out loud
python -m src.main run "ls" --a11y-backend stream        # write announcements to a stream
python -m src.main run "ls" --config ./config.toml       # explicit config file
```

Configuration is layered: a `config.toml` (see `configs/config.toml` for the schema) is overlaid by `TTYDIFF_*` environment variables (e.g. `TTYDIFF_THEME`, `TTYDIFF_ROWS`, `NO_COLOR`), which are in turn overridden by CLI flags.

## Honest Limits & Disclosures
In the spirit of the Zero Dependency Hackathon, we've implemented the core components ourselves. However, this means we've intentionally scoped out certain features:

1. **PTY is Unix-only**: We use Python's built-in `pty` module (Unix/macOS/WSL). On **native Windows** the runner transparently falls back to buffered `subprocess`, so the suite and CI run everywhere, but programs may suppress ANSI codes and TUIs won't behave like a real terminal. We deliberately do *not* pull in a `winpty` shim, to keep the zero-dependency guarantee.
2. **Parser Scope Cuts**: We only support basic cursor movement, erase codes (`ED`/`EL`), and SGR color/style codes. We explicitly do *not* support mouse tracking, bracketed paste mode, alternate screen buffers, or exotic private modes.
3. **Screen Reset**: The virtual screen resets to blank before each new command in a sequence rather than carrying the state over.
4. **Text-to-Speech is best-effort**: Accessibility announcements shell out to whatever OS speech tool is present (`say`/`spd-say`/`espeak`/PowerShell SAPI). We do *not* bundle a speech engine, so on a machine with none installed the speech backend is unavailable (the stream/null backends still work).

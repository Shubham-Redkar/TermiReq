# TermiReq (tyydiff)

**TermiReq** (also known as `tyydiff`) is a semantic diffing engine for terminal screens built entirely using Python's standard library. 

It reads the raw byte stream a terminal program emits (including ANSI/VT100 escape sequences), maintains a virtual screen model, and reports **only what changed** between frames. This provides the foundational layer that a real screen reader or terminal-monitoring tool would sit on top of.

## Features

- **ANSI/VT100 Parsing:** Decodes hidden terminal codes.
- **Virtual Screen:** Builds a 2D model of what is on the screen at any moment.
- **Semantic Diffing:** Compares two moments in time and reports only structural changes (including character and style changes).
- **Sequential Command Runner:** Feed it a list of shell commands, and it runs them one after another through a real pseudo-terminal (PTY) so programs emit full formatting, printing a diff summary after each.

## Usage

```bash
# Run multiple commands sequentially and diff their output
python -m src.main run "ls -la" "htop" "git status"
```

## Honest Limits & Disclosures
In the spirit of the Zero Dependency Hackathon, we've implemented the core components ourselves. However, this means we've intentionally scoped out certain features:

1. **Unix-only PTY**: We use Python's built-in `pty` module which is Unix-only. Windows is not supported.
2. **Parser Scope Cuts**: We only support basic cursor movement, erase codes (`ED`/`EL`), and SGR color/style codes. We explicitly do *not* support mouse tracking, bracketed paste mode, alternate screen buffers, or exotic private modes.
3. **Screen Reset**: The virtual screen resets to blank before each new command in a sequence rather than carrying the state over.
4. **No Text-to-Speech**: This project builds the *data layer* for accessibility tools, not the actual audio synthesis output.

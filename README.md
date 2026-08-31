# TermiReq

**TermiReq** is a tool that shows you exactly what changed on your terminal screen after running a command. It's like "git diff" but for terminal output — it highlights every character that appeared, disappeared, or moved.

Built entirely with Python's standard library. No installation needed. No internet required.

**Hackathon Track:** B — Terminal Accessibility Tool  
**License:** MIT (see [LICENSE](LICENSE))  
**Python:** 3.11 or later

---

## Table of Contents

1. [What Does This Tool Do?](#what-does-this-tool-do)
2. [Step-by-Step Setup](#step-by-step-setup)
3. [How to Use It](#how-to-use-it)
4. [All Commands (Reference)](#all-commands-reference)
5. [Features](#features)
6. [Honest Limits](#honest-limits)
7. [How It Works (Technical)](#how-it-works-technical)
8. [Bonus Challenges](#bonus-challenges)

---

## What Does This Tool Do?

Imagine you run a command like `ls -la` in your terminal. Normally, you just see the output. But with TermiReq, you see **exactly what changed** on the screen — which characters appeared, which ones disappeared, and where the cursor moved.

**Why is this useful?**
- **Accessibility:** A screen reader can use this to tell a blind user what changed on screen
- **Debugging:** See exactly what a command did to your terminal
- **Testing:** Verify that a program's output is correct

### Example Output

When you run `echo hello`, TermiReq shows:

```
--- Command 'echo hello' finished (exit code 0) ---
  Row 00 Col 00: '<space>' -> 'h'
  Row 00 Col 01: '<space>' -> 'e'
  Row 00 Col 02: '<space>' -> 'l'
  Row 00 Col 03: '<space>' -> 'l'
  Row 00 Col 04: '<space>' -> 'o'
```

This means: "On row 0, columns 0-4 changed from blank spaces to the letters h-e-l-l-o."

---

## Step-by-Step Setup

### Step 1: Check if Python is Installed

Open your computer's **Terminal** (also called Command Prompt or PowerShell):

- **Windows:** Press `Windows key`, type `cmd` or `PowerShell`, press Enter
- **Mac:** Press `Cmd + Space`, type `Terminal`, press Enter
- **Linux:** Press `Ctrl + Alt + T` (usually works)

Then type this command and press Enter:

```bash
python --version
```

You should see something like `Python 3.11.5`. If you see an error, install Python from [python.org](https://www.python.org/downloads/) (version 3.11 or later).

### Step 2: Download This Project

Click the green **Code** button on GitHub, then **Download ZIP**. Extract the ZIP file somewhere you can find it (like your Desktop).

Or if you know Git:

```bash
git clone https://github.com/Shubham-Redkar/TermiReq.git
cd TermiReq
```

### Step 3: Open a Terminal in the Project Folder

- **Windows:** Open the folder, hold `Shift` + right-click in an empty space, choose "Open PowerShell window here"
- **Mac/Linux:** Open Terminal, type `cd ` (with a space), then drag the folder into the Terminal window and press Enter

### Step 4: Run Your First Command

Type this and press Enter:

```bash
python termireq.py run "echo hello"
```

You should see output like:

```
--- Command 'echo hello' finished (exit code 0) ---
  Row 00 Col 00: '<space>' -> 'h'
  Row 00 Col 01: '<space>' -> 'e'
  Row 00 Col 02: '<space>' -> 'l'
  Row 00 Col 03: '<space>' -> 'l'
  Row 00 Col 04: '<space>' -> 'o'
```

**Congratulations!** TermiReq is working.

---

## How to Use It

### Run a Single Command

```bash
python termireq.py run "your command here"
```

Examples:

```bash
python termireq.py run "echo hello world"
python termireq.py run "ls -la"
python termireq.py run "dir"                    # Windows
python termireq.py run "python --version"
```

### Run Multiple Commands (One After Another)

Separate commands with spaces (each in quotes):

```bash
python termireq.py run "echo first" "echo second" "echo third"
```

TermiReq runs them in order and shows the diff after each one.

### Save a Session to a File

Record everything that happens (including hidden codes):

```bash
python termireq.py record -o mysession.bin "echo recorded"
```

This creates a file called `mysession.bin` with the raw terminal output.

### Replay a Saved Session

Play back a recorded session:

```bash
python termireq.py replay mysession.bin
```

### Make It Speak (Accessibility)

Have your computer read the changes out loud:

```bash
python termireq.py run "echo hello" --speak
```

On Mac, this uses the `say` command. On Windows, it uses PowerShell's speech. On Linux, it uses `spd-say` or `espeak`.

### Disable Colors

If you see weird symbols in the output:

```bash
python termireq.py run "echo hello" --no-color
```

### Set a Timeout

Stop a command if it takes too long (5.5 seconds):

```bash
python termireq.py run "sleep 10" --timeout 5.5
```

### Verbose Logging

See what TermiReq is doing behind the scenes:

```bash
python termireq.py run "echo hello" -v        # INFO level
python termireq.py run "echo hello" --debug   # DEBUG level
```

---

## All Commands (Reference)

| Command | What It Does | Example |
|---------|-------------|---------|
| `run` | Run commands and show what changed | `python termireq.py run "ls"` |
| `record` | Run a command and save raw output to a file | `python termireq.py record -o out.bin "ls"` |
| `replay` | Play back a recorded session | `python termireq.py replay out.bin` |

### Command-Line Flags

| Flag | Description | Example |
|------|-------------|---------|
| `--timeout N` | Stop command after N seconds | `--timeout 5` |
| `--json` | Output as machine-readable JSON | `--json` |
| `--no-color` | Disable colored output | `--no-color` |
| `--config PATH` | Use a custom config file | `--config ./config.toml` |
| `--speak` | Read changes out loud | `--speak` |
| `--accessibility` | Enable accessibility announcements | `--accessibility` |
| `--a11y-backend` | Choose: `auto`, `speech`, `stream`, `null` | `--a11y-backend stream` |
| `-v` / `--verbose` | Show info-level logs | `-v` |
| `--debug` | Show debug-level logs | `--debug` |

---

## Building the .pyz Artifact (Optional)

The `.pyz` file is a packaged version of TermiReq that runs the same way:

```bash
python -m zipapp termireq.py -o termireq.pyz -p "/usr/bin/env python3" -c
```

Then run it:

```bash
python termireq.pyz run "echo hello"
```

Verify the build is reproducible (same hash every time):

```bash
python -c "import hashlib,sys; e=open('termireq.pyz.sha256').read().strip(); a=hashlib.sha256(open('termireq.pyz','rb').read()).hexdigest(); print('Expected:',e); print('Actual:  ',a); sys.exit(0 if e==a else 1)"
```

---

## Running the Tests (For Developers)

To make sure everything works:

```bash
python -m unittest discover -s tests -p "test_*.py"
```

You should see something like:

```
Ran 167 tests in 5.9s
OK (skipped=1)
```

The "skipped=1" is normal — it's a test that only runs on Unix systems with a real terminal.

---

## Features

| Feature | Description |
|---------|-------------|
| **ANSI/VT100 Parsing** | Decodes hidden terminal codes (colors, cursor movement, etc.) |
| **Virtual Screen** | Builds a 2D grid of what's on screen at any moment |
| **Semantic Diffing** | Compares two moments and reports only what changed |
| **Sequential Runner** | Runs multiple commands one after another |
| **Colorized Output** | Highlights changes in red/green (respects `NO_COLOR`) |
| **Accessibility** | Speaks changes out loud using your OS's speech engine |
| **Record & Replay** | Save terminal sessions and play them back later |
| **Timeouts** | Prevents commands from hanging forever |
| **Config File** | Customize behavior with `config.toml` + environment variables |
| **Cross-Platform** | Works on Windows, Mac, and Linux |

---

## Honest Limits

We built everything from scratch using only Python's standard library. This means:

1. **PTY (pseudo-terminal) is Unix-only.** On Windows, we fall back to a simpler method. Commands still work, but some programs may not show colors.
2. **Basic terminal codes only.** We support common codes (cursor, colors, erase) but not exotic ones (mouse tracking, etc.).
3. **Screen resets between commands.** Each command starts with a blank screen.
4. **Speech is best-effort.** We use whatever speech tool your OS has. If none is installed, speech won't work (but everything else still does).

---

## How It Works (Technical)

For developers who want to understand the architecture:

1. **Runner** (`runner.py`) — Spawns shell commands through a real pseudo-terminal (PTY) on Unix, or buffered subprocess on Windows
2. **Parser** (`parser.py`) — Reads raw terminal bytes and turns them into structured events (print character, move cursor, set color, etc.)
3. **Screen** (`screen.py`) — Maintains a 2D grid of characters and styles, applying parser events to build a snapshot
4. **Diff** (`diff.py`) — Compares two screen snapshots cell-by-cell, detecting changes, scrolls, and cursor movement
5. **Accessibility** (`accessibility.py`) — Converts diffs into spoken announcements through OS speech services
6. **Config** (`config.py`) — Loads settings from `config.toml` + environment variables
7. **CLI** (`cli.py`) — Ties everything together with `argparse` command-line interface

All of this is in one file: `termireq.py` (Single File bonus challenge).

---

## Bonus Challenges

| Challenge | Points | Status |
|-----------|--------|--------|
| **Package Killer** | +3 | Replaced 10+ third-party packages (see STDLIB.md) |
| **STDLIB Log** | +3 | Documented all stdlib substitutions in STDLIB.md |
| **Single File** | +5 | Entire solution in `termireq.py` |
| **Reproducible Build** | +5 | `python -m zipapp` produces bit-for-bit identical artifacts |

---

## License

MIT License — free to use, modify, and distribute. See [LICENSE](LICENSE) for details.

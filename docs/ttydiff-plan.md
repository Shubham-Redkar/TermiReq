# ttydiff — Execution Plan
**Zero Dependency Hackathon · Track B (Parsers & Data Formats)**
Team: Siddhesh · Sarvesh · Shubham (Lead)
Language: Python (stdlib only)
Timeline: Tomorrow morning → Code freeze, Aug 31, 18:00 UTC

---

## 1. What We're Building

A semantic diffing engine for terminal screens. It reads the raw byte stream a terminal program emits (including ANSI/VT100 escape sequences), maintains a virtual screen model, and reports **only what changed** between frames — the layer a real screen reader or terminal-monitoring tool would sit on top of.

Bonus feature: a **sequential command runner** — feed it a list of shell commands, it runs them one after another through a real pseudo-terminal (so programs emit full color/cursor codes instead of detecting a pipe and going plain-text), and prints a diff summary after each.

**Not building:** actual text-to-speech output as a core/graded feature. Any audio demo is an optional, clearly disclosed flourish that degrades gracefully to text-only — never part of the compliance-critical path.

---

## 2. Architecture

```
raw bytes → [1] ANSI Parser → [2] Virtual Screen State → [3] Diff Engine → output
                                       ↑
                             [4] PTY Command Runner (feeds real command output in)
                                       ↑
                             [5] CLI / sequential command harness
```

| # | Component | Owner |
|---|---|---|
| 1 | ANSI/VT100 escape sequence parser | Siddhesh |
| 2 | Virtual screen state (grid model) | Siddhesh |
| 3 | Frame diff engine | Sarvesh |
| 4 | PTY-based command runner | Sarvesh |
| 5 | CLI, sequential command harness, integration | Shubham |
| — | Tests, README, STDLIB.md, demo video | Shubham (owns), all contribute |

---

## 3. Role Assignments

### Siddhesh — ANSI Parser + Virtual Screen (the core Track B craft)

**Owns:** `parser.py`, `screen.py`

**Scope (lock this on Day 1, document the cut in STDLIB.md):**
- Cursor movement: `CUU`/`CUD`/`CUF`/`CUB` (up/down/forward/back), `CUP` (absolute position)
- Erase: `ED` (erase display), `EL` (erase line)
- SGR color/style codes (`\x1b[31m`, bold, reset, etc.)
- Basic scroll region handling
- Save/restore cursor (`DECSC`/`DECRC`)

**Explicitly out of scope (say so plainly, don't hide it):** mouse tracking, bracketed paste mode, alternate screen buffer, exotic private modes. This is the honest-gap disclosure the scoring rewards.

**Deliverable:** a byte stream in → structured event stream out (`PrintChar`, `MoveCursor`, `SetColor`, `ClearScreen`, `ScrollRegion`, `SaveCursor`, `RestoreCursor`), plus a 2D grid (`screen.py`) that applies those events and tracks cursor position, per-cell character + style.

**Critical requirement:** keep a running byte offset and line/column counter from character one. Retrofitting error-position tracking later is miserable — build it in from the first commit.

---

### Sarvesh — Diff Engine + PTY Runner

**Owns:** `diff.py`, `runner.py`

**Diff engine (`diff.py`):**
- Takes two virtual screen states (before/after a chunk of output)
- Produces a minimal, structured diff: which rows/cells changed, what the new content is
- Needs to handle: partial line updates, scroll (don't report every line as "changed" just because everything shifted up one row — detect scroll as scroll), and cursor-only moves with no content change

**PTY runner (`runner.py`):**
- Uses `pty` (stdlib, Unix-only — disclose this platform limitation in README) to spawn each command with a real pseudo-terminal attached, so programs don't detect a pipe and suppress color/cursor codes
- Streams the command's raw output into Siddhesh's parser in real time
- Handles command exit, timeout, and Ctrl+C-to-skip
- Runs a list of commands strictly sequentially — one finishes (or is skipped) before the next starts

**Deliverable:** given a list of commands, execute each through a pty, feed output through the parser/screen/diff pipeline, and emit a clean diff report per command.

---

### Shubham (Lead) — CLI, Harness, Integration, Deliverables

**Owns:** `cli.py`, `main.py`, all submission artifacts

**CLI surface:**
```
ttydiff run "ls -la" "htop" "git status"
ttydiff run --file commands.txt
ttydiff replay session.log        # replay a captured raw byte log for testing/demo
```
- Argument parsing via `argparse`
- Clean exit codes, stdout/stderr separation
- `NO_COLOR` support if you colorize diff output

**Integration responsibilities:**
- Wires Siddhesh's parser/screen into Sarvesh's diff/runner into one working pipeline
- Runs daily integration checks so the three pieces don't drift apart until Day 3
- Owns the test corpus strategy: a folder of "ugly" captured terminal sessions (real output from `vim`, `htop`, `ls --color`, malformed/truncated sequences) run through `unittest` subtests

**Deliverables (all required by the pack):**
- `README.md` — what it does, how to run it, honest limits (parser scope cuts, Unix-only pty, no alt-screen support)
- `STDLIB.md` — every substitution, with rationale (see draft below)
- `Makefile` / one-command build
- `deps-proof.txt` — proof of zero third-party deps
- `.zero-dep.toml` — track letter (B), one-line pitch
- 5-minute demo video: show `ttydiff run` chaining real commands, show the diff output, show the empty manifest

---

## 4. STDLIB.md Draft (start filling this in Day 1)

| Normally you'd install | Instead | Why |
|---|---|---|
| A terminal emulation library (e.g. `pyte`) | Hand-rolled `parser.py` + `screen.py` | The parser/screen model *is* the project — this is the whole point of Track B |
| `python-Levenshtein` / diff libraries for text | Custom cell-grid diff in `diff.py` | Terminal diffing needs cursor/scroll awareness a generic text diff doesn't have |
| `pexpect` (pty automation) | `pty` (stdlib) + `subprocess` | Real pseudo-terminal without a wrapper library |
| `click` / `typer` | `argparse` | CLI surface |
| `colorama` (cross-platform ANSI) | Raw ANSI escapes, `NO_COLOR` check | Output styling |
| `sh` / `plumbum` (shell command chaining) | `subprocess` + `pty` directly | Sequential command execution |

*(Target: 10 real substitutions for the +3 STDLIB Log bonus — add more as you hit real decision points, e.g. how you handle wide characters, how you timestamp events.)*

---

## 5. Day-by-Day Timeline

### Day 1 (Tomorrow) — Morning to Night: Foundations, no integration yet

**Morning (all three, together, ~1–2 hrs):**
- Confirm architecture and interfaces between modules (exact function signatures/data shapes each person hands off — agree this *before* splitting, so Day 3 integration doesn't blow up)
- Set up repo skeleton: `src/`, `tests/`, `README.md`, `STDLIB.md`, `.zero-dep.toml`, empty `requirements.txt`
- Agree on the event data structure passed from parser → screen → diff (e.g. a simple dataclass or named tuple per event type)

**Rest of Day 1 (solo work):**
- **Siddhesh:** Start the parser. Get basic cursor movement + printable character handling working. Byte-offset/line-column tracking from the start.
- **Sarvesh:** Start the PTY runner in isolation — spawn a single hardcoded command (`ls`), confirm you get real ANSI codes back (not suppressed). This de-risks the trickiest infra piece early.
- **Shubham:** Build the CLI skeleton (`argparse` setup, `run` subcommand accepting multiple command strings) and the test harness scaffolding (`unittest` structure, how test fixtures/captured sessions will be stored).

**End of Day 1 checkpoint:** Siddhesh can parse basic cursor + print events from a hardcoded byte string. Sarvesh can spawn one command via pty and capture its raw output. Shubham's CLI parses args and prints them (no real logic yet).

---

### Day 2 — Core Build + First Integration

**Morning:**
- **Siddhesh:** Extend parser to cover SGR colors, `ED`/`EL` erase codes, scroll regions. Build `screen.py` grid model that consumes parser events and maintains cursor position + cell state.
- **Sarvesh:** Extend runner to accept a *list* of commands and run them strictly sequentially. Start `diff.py` — basic cell-by-cell diff between two screen states.
- **Shubham:** Wire CLI's `run` command to call the runner with the parsed command list. Start collecting the test corpus: capture real raw output from `vim`, `htop`, `ls --color=always`, `git status` using `script` or manual pty capture (for use as fixture files, not for shelling out at runtime).

**Afternoon — First integration checkpoint (all three):**
- Plug Siddhesh's parser+screen into Sarvesh's runner+diff, driven by Shubham's CLI
- Run one real command end-to-end: `ttydiff run "ls --color"` → should produce a real diff report
- **This is the most important moment in the whole plan.** Fix interface mismatches now, not on Day 3.

**Evening:**
- **Siddhesh:** Handle edge cases found during integration — malformed/truncated sequences, wide characters if they came up
- **Sarvesh:** Improve diff quality — detect scroll vs. full-redraw, avoid over-reporting changes
- **Shubham:** Start writing `unittest` subtests against the captured fixture corpus; draft README structure

---

### Day 3 — Hardening, Tests, Docs, Demo

**Morning:**
- **Siddhesh:** Freeze parser scope. Focus remaining time on test coverage for parser edge cases (malformed input, unsupported sequences failing gracefully rather than crashing) and error-position reporting quality.
- **Sarvesh:** Freeze diff engine scope. Add handling for command timeout / Ctrl+C-to-skip in the runner. Test with a longer command chain (5+ commands).
- **Shubham:** Finalize `README.md` (what it does, how to run, honest limits section — explicitly list unsupported ANSI features and the Unix-only `pty` limitation), finalize `STDLIB.md` with all real substitutions and rationale, write `deps-proof.txt` (e.g. output of a script confirming no third-party imports), fill in `.zero-dep.toml`.

**Afternoon:**
- All three: full run-through of the tool live, exactly as a judge would run it — one command builds/runs it, manifest is empty, demo scenario works
- Record the 5-minute demo video: show `ttydiff run` chaining 3–4 real commands (pick visually distinct ones — `ls --color`, something with cursor movement, something with scrolling output), show the diff output per command, show the empty dependency manifest and `deps-proof.txt`
- If doing the optional audio flourish: demo it clearly labeled as optional/disclosed, degrading gracefully if `say`/`espeak` isn't present — never implied as part of the graded core

**Before submission:**
- Final check: does the whole thing build and run with **one command**? (a judge should not have to read your CI to figure out how to run it)
- Final check: is the manifest actually empty, and does `deps-proof.txt` prove it in under 5 seconds of reading?
- Submit: public GitHub repo, README, STDLIB.md, tests/, build command, deps-proof.txt, demo video

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| Parser scope creep (trying to handle every ANSI sequence) | Scope locked Day 1 morning; anything outside the list is explicitly out-of-scope and disclosed, not silently missing |
| Day 3 integration disaster | First integration checkpoint happens Day 2 afternoon, not Day 3 — surfaces interface mismatches while there's still time to fix them |
| `pty` being Unix-only | Disclosed upfront in README as a known platform limitation; if any team member is on Windows, they develop via WSL |
| Diff engine over-reporting (everything looks "changed" on scroll) | Sarvesh treats scroll detection as a first-class case, not an afterthought, since it's the difference between a useful diff and a noisy one |
| Running out of time for tests | Test corpus building starts Day 2 morning in parallel with feature work, not bolted on at the end |

---

## 7. Track B Scoring Alignment (why this plan targets the rubric)

- **Functionality & Usefulness (35%):** Real commands run through it live in the demo, producing real diffs — not a synthetic toy example
- **Zero-Dependency Craft (30%):** Every "normally I'd install X" moment goes into STDLIB.md with rationale; targeting 10+ for the STDLIB Log bonus
- **Code Quality & Idiom (25%):** Clean separation (parser / screen / diff / runner / CLI) reads as intentional architecture, not a monolith
- **Innovation (10%):** A terminal-diffing engine as the foundation for accessibility tooling is a genuinely surprising "didn't know you could do that without a package" angle

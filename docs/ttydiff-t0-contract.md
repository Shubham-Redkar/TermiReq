# T0 — The Data Contract (Detailed)

**Goal of this meeting:** by the end of this hour, all three of you can go write code separately and your pieces will fit together without guessing. Nobody starts on T1/T2/T5 until this is agreed and written down somewhere all three can see (a shared doc, or straight into a `contracts.py` / `types.py` file in the repo).

This isn't a brainstorm — it's a checklist of exact shapes to agree on. Go through it in order.

---

## 1. Shared basics (used everywhere)

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class Style:
    fg_color: str | None = None   # e.g. "red", "green" — keep it simple, no RGB math needed
    bg_color: str | None = None
    bold: bool = False

@dataclass
class Cell:
    char: str              # single character; " " (space) means empty
    style: Style = field(default_factory=Style)
```

**Decide out loud:** do colors get stored as simple names (`"red"`) or raw ANSI numbers (`31`)? → **Recommendation: simple names.** Easier to read in tests and diffs, and the parser translates the ANSI number into a name once, at the source.

---

## 2. Parser Events — what Siddhesh's parser hands to the screen

The parser reads raw bytes and turns them into a stream of these events, one at a time, in order:

```python
from dataclasses import dataclass
from typing import Union

@dataclass
class PrintChar:
    char: str
    style: Style
    byte_offset: int        # position in the raw input this came from

@dataclass
class MoveCursor:
    row: int
    col: int
    absolute: bool           # True = jump to exact position (CUP), False = relative move
    byte_offset: int

@dataclass
class ClearScreen:
    mode: int                # 0 = cursor→end, 1 = start→cursor, 2 = whole screen
    byte_offset: int

@dataclass
class ClearLine:
    mode: int
    byte_offset: int

@dataclass
class SetStyle:
    style: Style              # the new style to apply going forward
    byte_offset: int

@dataclass
class SaveCursor:
    byte_offset: int

@dataclass
class RestoreCursor:
    byte_offset: int

@dataclass
class UnknownSequence:
    raw_bytes: bytes
    byte_offset: int
    # The parser must NEVER crash on something it doesn't recognize —
    # it emits this event and keeps going. This is what "handles ugly
    # edge cases" means for Track B scoring.

ParserEvent = Union[
    PrintChar, MoveCursor, ClearScreen, ClearLine,
    SetStyle, SaveCursor, RestoreCursor, UnknownSequence
]
```

**Decide out loud — naming clash to avoid:** `byte_offset` here means "position in the raw command output," **not** the same thing as screen row/col. Call the raw-stream position `byte_offset` everywhere, and screen position `row`/`col` everywhere, and never let the two get called the same thing in code or conversation. This exact confusion is where Track B error-position tracking usually goes wrong.

**Decide out loud:** scroll-region handling — in scope for Day 1, or cut immediately per the priority list? → If cutting per the earlier plan, skip a `ScrollRegion` event entirely for v1 and don't build for it. Don't leave it half-defined.

---

## 3. Screen State — what Siddhesh's screen.py owns

```python
@dataclass
class ScreenState:
    rows: int
    cols: int
    grid: list[list[Cell]]     # grid[row][col]
    cursor_row: int
    cursor_col: int

    def snapshot(self) -> "ScreenState":
        # MUST be a deep copy — this is what makes before/after diffing possible.
        # If this is a shallow copy, the diff engine will compare a state
        # against itself and always report "nothing changed."
        ...
```

**Decide out loud — this one is easy to get wrong:**
- `apply_event(state, event)` — does it **mutate the state in place** and return `None`, or return a **new** `ScreenState`? → **Recommendation: mutate in place** for simplicity and speed, but that makes `snapshot()` non-negotiable before every diff comparison. Say this explicitly so Sarvesh doesn't accidentally diff a state against itself.
- **Reset behavior between commands:** does the virtual screen reset to blank before each command in the sequence, or carry over from the previous command's final state? → **Recommendation for v1: reset to blank before each command.** Carrying state over is more realistic but adds complexity neither of you has time for in 2 days. Document this as a stated limitation in the README, not a silent gap.

---

## 4. Diff Output — what Sarvesh's diff.py hands to the CLI

```python
@dataclass
class CellChange:
    row: int
    col: int
    old: Cell
    new: Cell

@dataclass
class DiffResult:
    changes: list[CellChange]
    cursor_moved: bool
    new_cursor: tuple[int, int]
    # scroll: only add this field if scroll detection made it into scope

def diff_screens(before: "ScreenState", after: "ScreenState") -> DiffResult:
    ...
```

**Decide out loud:** what counts as "changed" — a full `Cell` comparison (char AND style), or char-only? → **Recommendation: full `Cell` comparison.** A color-only change (e.g. a progress bar going from yellow to green with the same character) is exactly the kind of thing a screen reader / monitoring tool would care about, and it's cheap to compare since `Style` is already a frozen dataclass (comparable with `==` for free).

**Decide out loud:** does Sarvesh build T4 against a real `ScreenState`, or a hand-written **mock** matching this shape so he isn't blocked waiting on Siddhesh? → **Must be the mock.** Write 2-3 fake `ScreenState` objects by hand right now, in this meeting, so Sarvesh can start immediately after T0 ends.

---

## 5. Runner Events — what Sarvesh's runner.py hands to the parser/CLI

```python
@dataclass
class CommandChunk:
    command: str
    data: bytes           # raw bytes as they arrive from the pty
    command_index: int    # 0-based position in the sequence

@dataclass
class CommandFinished:
    command: str
    command_index: int
    exit_code: int

RunnerEvent = Union[CommandChunk, CommandFinished]

def run_commands(commands: list[str]):
    """
    Yields RunnerEvent objects.
    Spawns each command via pty, one at a time — the next command
    must not start until CommandFinished has been yielded for the current one.
    """
```

**Decide out loud:** does the CLI hand the parser raw bytes chunk-by-chunk as they stream in (live), or does the runner buffer a whole command's output and hand it over once the command finishes? → **Recommendation for v1: buffer per command.** Streaming live is the "correct" real-time design but adds timing complexity you don't need — you only need a before/after diff per command, not live updates mid-command. State this as the v1 scope, with live streaming as a stretch goal if time allows.

---

## 6. The T0 Meeting — run it as this exact checklist

Go through these five questions out loud, in this order, and don't leave the room until each has a one-line answer written down:

1. **Colors:** names (`"red"`) or raw codes? → *(recommend: names)*
2. **Mutation:** does `apply_event` mutate in place, or return new state? → *(recommend: mutate in place, snapshot before diffing)*
3. **Reset behavior:** does the screen reset between commands, or carry over? → *(recommend: reset — document as a limitation)*
4. **Diff granularity:** char-only or full cell (char + style)? → *(recommend: full cell)*
5. **Streaming vs buffered:** does output get parsed live or after the command finishes? → *(recommend: buffered per command for v1)*

Once these five are answered, write the type definitions above into a `contracts.py` file in the repo, commit it, and only then split up to start T1/T2/T5 in parallel.

---

## Why this level of detail matters with 2 days

Every one of these five decisions, if left ambiguous, becomes a bug discovered at **Integration A** — which is exactly the moment you can't afford to lose time. Answering them now, even if a recommendation turns out wrong later, is cheaper than discovering three different assumptions baked into three different modules on Day 1 evening.

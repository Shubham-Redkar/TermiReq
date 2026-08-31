#!/usr/bin/env python3
"""TermiReq — Semantic terminal-screen diffing engine (single file, stdlib only).

Complete, self-contained implementation of TermiReq. All modules merged into
this single file for the Zero Dependency Hackathon "Single File" bonus challenge.

Usage:
    python termireq.py run "ls -la"
    python termireq.py record -o session.bin "htop"
    python termireq.py replay session.bin

Build (reproducible):
    make build          # produces termireq.pyz + SHA256 hash
    python termireq.pyz run "echo hello"

See README.md for full documentation and STDLIB.md for the stdlib
substitution log.
"""

from __future__ import annotations

# ── stdlib imports (all that any merged module needs) ────────────────────────
import argparse
import dataclasses
import errno
import json
import logging
import os
import platform
import select
import shutil
import signal
import struct
import subprocess
import sys
import time
import unicodedata
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Callable, Iterable, Iterator, List, Mapping, Optional, Sequence,
    TextIO, Tuple, Union,
)

if sys.platform != "win32":
    import fcntl
    import termios


# ════════════════════════════════════════════════════════════════════════════ #
#  CONTRACTS — shared data types (dataclasses)                                #
# ════════════════════════════════════════════════════════════════════════════ #


@dataclass(frozen=True)
class Style:
    """Represents the styling (color, boldness) of a terminal cell."""
    fg_color: str | None = None
    bg_color: str | None = None
    bold: bool = False


@dataclass
class Cell:
    """Represents a single character cell on the virtual terminal screen."""
    char: str
    style: Style = field(default_factory=Style)


@dataclass
class PrintChar:
    char: str
    style: Style
    byte_offset: int


@dataclass
class MoveCursor:
    row: int
    col: int
    absolute: bool
    byte_offset: int


@dataclass
class ClearScreen:
    mode: int
    byte_offset: int


@dataclass
class ClearLine:
    mode: int
    byte_offset: int


@dataclass
class SetStyle:
    style: Style
    byte_offset: int


@dataclass
class SaveCursor:
    byte_offset: int


@dataclass
class RestoreCursor:
    byte_offset: int


@dataclass
class SetTitle:
    title: str
    byte_offset: int


@dataclass
class UnknownSequence:
    raw_bytes: bytes
    byte_offset: int


@dataclass
class SwitchToAlternateScreen:
    byte_offset: int


@dataclass
class SwitchToMainScreen:
    byte_offset: int


ParserEvent = Union[
    PrintChar,
    MoveCursor,
    ClearScreen,
    ClearLine,
    SetStyle,
    SaveCursor,
    RestoreCursor,
    SetTitle,
    SwitchToAlternateScreen,
    SwitchToMainScreen,
    UnknownSequence,
]


@dataclass
class ScreenState:
    """Maintains the 2D grid of Cells and current cursor position."""
    rows: int
    cols: int
    grid: list[list[Cell]]
    cursor_row: int
    cursor_col: int
    title: str | None = None
    is_alt_screen: bool = False
    _main_grid: list[list[Cell]] | None = None
    _main_cursor_row: int = 0
    _main_cursor_col: int = 0

    @classmethod
    def blank(cls, rows: int, cols: int) -> ScreenState:
        """Create a blank screen of given dimensions."""
        return cls(
            rows=rows, cols=cols,
            grid=[[Cell(" ") for _ in range(cols)] for _ in range(rows)],
            cursor_row=0, cursor_col=0,
        )

    def snapshot(self) -> ScreenState:
        """Return a deep copy for before/after diff comparisons."""
        snap = ScreenState(
            rows=self.rows,
            cols=self.cols,
            grid=[
                [Cell(char=cell.char, style=cell.style) for cell in row]
                for row in self.grid
            ],
            cursor_row=self.cursor_row,
            cursor_col=self.cursor_col,
            title=self.title,
            is_alt_screen=self.is_alt_screen,
        )
        if self._main_grid is not None:
            snap._main_grid = [
                [Cell(char=cell.char, style=cell.style) for cell in row]
                for row in self._main_grid
            ]
            snap._main_cursor_row = self._main_cursor_row
            snap._main_cursor_col = self._main_cursor_col
        return snap


@dataclass
class CellChange:
    """Records a single mutated cell for the final diff output."""
    row: int
    col: int
    old: Cell
    new: Cell


@dataclass
class DiffResult:
    """The aggregate summary of all changes between two ScreenStates."""
    changes: list[CellChange]
    cursor_moved: bool
    new_cursor: tuple[int, int]
    scrolled: bool = False
    scroll_direction: str | None = None
    scroll_amount: int = 0


@dataclass(frozen=True)
class AccessibilityAnnouncement:
    """A semantic message destined for assistive technology."""
    text: str
    kind: str = "info"
    priority: str = "polite"
    command: str | None = None


@dataclass
class CommandChunk:
    """A raw byte chunk emitted by a running subprocess or PTY."""
    command: str
    data: bytes
    command_index: int


@dataclass
class CommandFinished:
    """Emitted when a subprocess completes its execution."""
    command: str
    command_index: int
    exit_code: int
    timed_out: bool = False
    skipped: bool = False


RunnerEvent = Union[CommandChunk, CommandFinished]


# ════════════════════════════════════════════════════════════════════════════ #
#  LOGGER — stdlib logging with custom stderr handler                         #
# ════════════════════════════════════════════════════════════════════════════ #

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

_configured: bool = False


class _CurrentStderrHandler(logging.Handler):
    """Writes every record to whatever ``sys.stderr`` currently points at."""

    terminator = "\n"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stderr.write(msg + self.terminator)
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger named ``termireq.<name>``."""
    prefix = "termireq"
    if name == prefix or name.startswith(prefix + "."):
        full = name
    else:
        full = f"{prefix}.{name}"
    return logging.getLogger(full)


def _resolve_level(verbose: bool, debug: bool, env_level: Optional[str]) -> int:
    """Combine CLI flags and env override into a logging level int."""
    if debug:
        return logging.DEBUG
    if verbose:
        return logging.INFO
    if env_level:
        return _LEVELS.get(env_level.strip().lower(), logging.WARNING)
    return logging.WARNING


def configure_logging(
    *,
    verbose: bool = False,
    debug: bool = False,
) -> logging.Logger:
    """Install the root ``termireq`` logger and return it."""
    root = logging.getLogger("termireq")
    root.setLevel(_resolve_level(verbose, debug, os.environ.get("TERMIREQ_LOG_LEVEL")))

    global _configured
    if not _configured:
        handler = _CurrentStderrHandler()
        handler.setFormatter(
            logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
        )
        root.addHandler(handler)
        _configured = True

    return root


# ════════════════════════════════════════════════════════════════════════════ #
#  PARSER — ANSI/VT100 escape-sequence parser                                 #
# ════════════════════════════════════════════════════════════════════════════ #

logger = get_logger("parser")

_FG_NAMES = {
    30: "black", 31: "red", 32: "green", 33: "yellow",
    34: "blue", 35: "magenta", 36: "cyan", 37: "white",
    90: "bright_black", 91: "bright_red", 92: "bright_green",
    93: "bright_yellow", 94: "bright_blue", 95: "bright_magenta",
    96: "bright_cyan", 97: "bright_white",
}


def _bg_name(code: int) -> str | None:
    if 40 <= code <= 47:
        return _FG_NAMES[code - 10]
    if 100 <= code <= 107:
        return _FG_NAMES[code - 10]
    return None


def _extended_name(code: int) -> str | None:
    if 0 <= code <= 15:
        return _FG_NAMES.get(30 + code) or _FG_NAMES.get(90 + (code - 8))
    if 232 <= code <= 255:
        return None
    return None


class ANSIParser:
    """Incrementally parse a terminal byte stream into a stream of events."""

    def __init__(self) -> None:
        self._current_style = Style()
        self._save_stack: List[Tuple[int, int]] = []

    def feed(self, data: bytes) -> Iterator[ParserEvent]:
        """Parse ``data`` and yield parser events in order."""
        i = 0
        n = len(data)
        while i < n:
            b = data[i]
            if b == 0x1B:
                i, events = self._consume_escape(data, i)
                yield from events
            elif b == 0x0A:
                i += 1
                yield PrintChar("\n", self._current_style, i - 1)
            elif b == 0x0D:
                i += 1
                yield PrintChar("\r", self._current_style, i - 1)
            elif b == 0x08:
                i += 1
                yield MoveCursor(0, -1, False, i - 1)
            elif b == 0x09:
                i += 1
                yield PrintChar("\t", self._current_style, i - 1)
            elif 0x20 <= b <= 0x7E:
                char = chr(b)
                i += 1
                yield PrintChar(char, self._current_style, i - 1)
            elif b >= 0x80:
                i, char = self._consume_utf8(data, i)
                if char is not None:
                    yield PrintChar(char, self._current_style, i - 1)
                else:
                    logger.debug("unknown UTF-8 sequence at byte %d", i - 1)
                    yield UnknownSequence(data[i - 1:i], i - 1)
            else:
                logger.debug("unknown control byte 0x%02X at byte %d", b, i - 1)
                i += 1
                yield UnknownSequence(data[i - 1:i], i - 1)

    def parse(self, data: bytes) -> List[ParserEvent]:
        """Single-shot convenience: parse a whole stream into a list of events."""
        events = list(self.feed(data))
        logger.debug("parsed %d bytes -> %d events", len(data), len(events))
        return events

    def _consume_escape(self, data: bytes, i: int) -> Tuple[int, List[ParserEvent]]:
        start = i
        n = len(data)
        if i + 1 >= n:
            return i + 1, [UnknownSequence(data[i:i + 1], i)]

        c = data[i + 1]
        if c == 0x5B:
            return self._consume_csi(data, i)
        if c == 0x5D:
            return self._consume_osc(data, i)
        if c == 0x37:
            return i + 2, [SaveCursor(i)]
        if c == 0x38:
            return i + 2, [RestoreCursor(i)]

        end = i + 2
        limit = min(n, i + 1024)
        while end < limit:
            b = data[end]
            if 0x20 <= b <= 0x7E:
                if 0x40 <= b <= 0x7E:
                    end += 1
                    break
                end += 1
            else:
                break
        return end, [UnknownSequence(data[start:end], start)]

    def _consume_osc(self, data: bytes, i: int) -> Tuple[int, List[ParserEvent]]:
        start = i
        n = len(data)
        j = i + 2

        payload = ""
        while j < n:
            if data[j] == 0x07:
                j += 1
                break
            if data[j] == 0x1B and j + 1 < n and data[j + 1] == 0x5C:
                j += 2
                break
            payload += chr(data[j])
            j += 1
        else:
            return n, [UnknownSequence(data[start:n], start)]

        if payload.startswith(("0;", "2;")):
            return j, [SetTitle(title=payload[2:], byte_offset=start)]

        return j, [UnknownSequence(data[start:j], start)]

    def _consume_csi(self, data: bytes, i: int) -> Tuple[int, List[ParserEvent]]:
        start = i
        n = len(data)
        j = i + 2

        private = False
        if j < n and data[j] in (0x3C, 0x3D, 0x3E, 0x3F):
            private = True
            j += 1

        params_str = ""
        while j < n and 0x30 <= data[j] <= 0x3F:
            params_str += chr(data[j])
            j += 1

        intermediate = ""
        while j < n and 0x20 <= data[j] <= 0x2F:
            intermediate += chr(data[j])
            j += 1

        if j >= n:
            return n, [UnknownSequence(data[start:n], start)]

        final = chr(data[j])
        j += 1

        if private:
            params = [int(p) if p else 0 for p in params_str.split(";")] if params_str else []
            if final == "h" and 1049 in params:
                return j, [SwitchToAlternateScreen(start)]
            if final == "l" and 1049 in params:
                return j, [SwitchToMainScreen(start)]
            return j, [UnknownSequence(data[start:j], start)]

        params: List[int] = []
        if params_str:
            params = [int(p) if p else 0 for p in params_str.split(";")]

        events = self._dispatch_csi(final, intermediate, params, start)
        return j, events

    def _dispatch_csi(
        self, final: str, intermediate: str, params: List[int], offset: int
    ) -> List[ParserEvent]:
        if intermediate:
            return [UnknownSequence(b"\x1b[", offset)]

        n = len(params)

        if final == "A":
            return [MoveCursor(-(params[0] if n else 1), 0, False, offset)]
        if final == "B":
            return [MoveCursor(params[0] if n else 1, 0, False, offset)]
        if final == "C":
            return [MoveCursor(0, params[0] if n else 1, False, offset)]
        if final == "D":
            return [MoveCursor(0, -(params[0] if n else 1), False, offset)]
        if final in ("H", "f"):
            row = (params[0] if n else 1) - 1
            col = (params[1] if n > 1 else 1) - 1
            return [MoveCursor(row, col, True, offset)]
        if final == "J":
            return [ClearScreen(params[0] if n else 0, offset)]
        if final == "K":
            return [ClearLine(params[0] if n else 0, offset)]
        if final == "m":
            return [SetStyle(self._apply_sgr(params, offset), offset)]
        if final == "s":
            return [SaveCursor(offset)]
        if final == "u":
            return [RestoreCursor(offset)]

        return [UnknownSequence(b"\x1b[", offset)]

    def _apply_sgr(self, params: List[int], offset: int) -> Style:
        style = self._current_style
        fg = style.fg_color
        bg = style.bg_color
        bold = style.bold

        if not params:
            params = [0]

        i = 0
        while i < len(params):
            p = params[i]
            if p == 0:
                fg, bg, bold = None, None, False
            elif p == 1:
                bold = True
            elif p == 22:
                bold = False
            elif p == 39:
                fg = None
            elif p == 49:
                bg = None
            elif 30 <= p <= 37 or 90 <= p <= 97:
                fg = _FG_NAMES.get(p, fg)
            elif 40 <= p <= 47 or 100 <= p <= 107:
                bg = _bg_name(p)
            elif p in (38, 48):
                extended = self._consume_extended_color(params, i)
                if extended is not None:
                    target, name = extended
                    if target == "fg":
                        fg = name if name is not None else fg
                    else:
                        bg = name if name is not None else bg
                # Skip past consumed params: 38/48 + mode + value(s)
                n = len(params)
                if i + 1 < n and params[i + 1] == 5:
                    i += 3  # 38;5;N or 48;5;N
                elif i + 1 < n and params[i + 1] == 2:
                    i += 6  # 38;2;R;G;B or 48;2;R;G;B
                else:
                    i += 1
                continue
            i += 1

        new_style = Style(fg_color=fg, bg_color=bg, bold=bold)
        self._current_style = new_style
        return new_style

    def _consume_extended_color(
        self, params: List[int], i: int
    ) -> Tuple[str, str | None] | None:
        n = len(params)
        target = "fg" if params[i] == 38 else "bg"
        if i + 1 >= n:
            return None
        if params[i + 1] == 5 and i + 2 < n:
            name = _extended_name(params[i + 2])
            return target, name
        return target, None

    @staticmethod
    def _consume_utf8(data: bytes, i: int) -> Tuple[int, str | None]:
        b0 = data[i]
        if b0 < 0x80:
            return i + 1, chr(b0)
        if 0xC2 <= b0 <= 0xDF:
            length = 2
        elif 0xE0 <= b0 <= 0xEF:
            length = 3
        elif 0xF0 <= b0 <= 0xF4:
            length = 4
        else:
            return i + 1, None
        if i + length > len(data):
            return len(data), None
        try:
            return i + length, data[i:i + length].decode("utf-8")
        except UnicodeDecodeError:
            return i + 1, None


def parse(data: bytes) -> List[ParserEvent]:
    """Parse a complete byte stream into a list of events."""
    return list(ANSIParser().feed(data))


# ════════════════════════════════════════════════════════════════════════════ #
#  SCREEN — virtual 2D screen grid                                            #
# ════════════════════════════════════════════════════════════════════════════ #

logger = get_logger("screen")

TAB_STOP = 8

Observer = Callable[[AccessibilityAnnouncement], None]


class DirtyRows:
    """Tracks which grid rows changed, for incremental diffing."""

    __slots__ = ("_rows", "all")

    def __init__(self) -> None:
        self._rows: set[int] = set()
        self.all: bool = False

    def add(self, row: int) -> None:
        self._rows.add(row)

    def mark_all(self) -> None:
        self.all = True
        self._rows.clear()
        logger.debug("dirty rows marked ALL (scroll/shift detected)")

    def clear(self) -> None:
        self._rows.clear()
        self.all = False

    def rows(self, total: int) -> list[int]:
        if self.all:
            return list(range(total))
        return sorted(r for r in self._rows if 0 <= r < total)

    def __bool__(self) -> bool:
        return self.all or bool(self._rows)


def _empty_row(cols: int) -> List[Cell]:
    return [Cell(" ") for _ in range(cols)]


def apply_event(
    state: ScreenState,
    event,
    observer: Optional[Observer] = None,
    dirty: Optional[DirtyRows] = None,
) -> None:
    """Apply a single parser event to ``state`` in place."""
    if isinstance(event, PrintChar):
        _print_char(state, event, dirty)
    elif isinstance(event, MoveCursor):
        _move_cursor(state, event)
    elif isinstance(event, ClearScreen):
        _clear_screen(state, event, dirty)
        if observer is not None and event.mode in (2, 3):
            observer(
                AccessibilityAnnouncement(text="Screen cleared.", kind="screen_cleared")
            )
    elif isinstance(event, ClearLine):
        _clear_line(state, event, dirty)
    elif isinstance(event, SaveCursor):
        state.__dict__["_saved_cursor"] = (state.cursor_row, state.cursor_col)
    elif isinstance(event, RestoreCursor):
        saved = state.__dict__.get("_saved_cursor")
        if saved is not None:
            state.cursor_row, state.cursor_col = saved
    elif isinstance(event, SetStyle):
        return
    elif isinstance(event, SetTitle):
        state.title = event.title
        logger.debug("title set: %r", event.title)
        if observer is not None:
            observer(
                AccessibilityAnnouncement(
                    text=f"Window title: {event.title}", kind="title"
                )
            )
    elif isinstance(event, SwitchToAlternateScreen):
        if not state.is_alt_screen:
            state._main_grid = state.grid
            state._main_cursor_row = state.cursor_row
            state._main_cursor_col = state.cursor_col
            state.grid = [[Cell(" ") for _ in range(state.cols)] for _ in range(state.rows)]
            state.cursor_row = 0
            state.cursor_col = 0
            state.is_alt_screen = True
            logger.debug("switched to alternate screen")
            if dirty is not None:
                dirty.mark_all()
    elif isinstance(event, SwitchToMainScreen):
        if state.is_alt_screen:
            if state._main_grid is not None:
                state.grid = state._main_grid
                state.cursor_row = state._main_cursor_row
                state.cursor_col = state._main_cursor_col
            state.is_alt_screen = False
            logger.debug("switched to main screen")
            if dirty is not None:
                dirty.mark_all()


def apply_events(
    state: ScreenState,
    events,
    observer: Optional[Observer] = None,
    dirty: Optional[DirtyRows] = None,
) -> None:
    """Apply a sequence of events to ``state`` in place."""
    for event in events:
        apply_event(state, event, observer, dirty)


def _print_char(
    state: ScreenState, event: PrintChar, dirty: Optional[DirtyRows] = None
) -> None:
    """Print a character to the screen, advancing the cursor and handling wraps."""
    rows, cols = state.rows, state.cols
    row, col = state.cursor_row, state.cursor_col

    if event.char == "\r":
        state.cursor_col = 0
        return
    if event.char == "\t":
        state.cursor_col = min(cols - 1, ((col // TAB_STOP) + 1) * TAB_STOP)
        return
    if event.char == "\n":
        if row + 1 < rows:
            state.cursor_row = row + 1
        else:
            state.grid.pop(0)
            state.grid.append(_empty_row(cols))
            if dirty is not None:
                dirty.mark_all()
        return

    if 0 <= row < rows and 0 <= col < cols:
        state.grid[row][col] = Cell(event.char, event.style)
        if dirty is not None:
            dirty.add(row)

        width = 0
        for ch in event.char:
            eaw = unicodedata.east_asian_width(ch)
            width += 2 if eaw in ('W', 'F') else 1

        if col + width < cols:
            state.cursor_col += width
        elif row + 1 < rows:
            state.cursor_row += 1
            state.cursor_col = 0
        else:
            state.grid.pop(0)
            state.grid.append(_empty_row(cols))
            state.cursor_col = 0
            if dirty is not None:
                dirty.mark_all()


def _move_cursor(state: ScreenState, event: MoveCursor) -> None:
    """Move the cursor absolutely or relatively, clamping to screen boundaries."""
    rows, cols = state.rows, state.cols
    if event.absolute:
        state.cursor_row = max(0, min(rows - 1, event.row))
        state.cursor_col = max(0, min(cols - 1, event.col))
        return
    new_row = max(0, min(rows - 1, state.cursor_row + event.row))
    new_col = max(0, min(cols - 1, state.cursor_col + event.col))
    state.cursor_row = new_row
    state.cursor_col = new_col


def _clear_screen(
    state: ScreenState, event: ClearScreen, dirty: Optional[DirtyRows] = None
) -> None:
    """Clear the screen (or a portion of it) depending on the event mode."""
    rows, cols = state.rows, state.cols
    r, c = state.cursor_row, state.cursor_col
    if event.mode == 0:
        for cc in range(c, cols):
            state.grid[r][cc] = Cell(" ")
        for rr in range(r + 1, rows):
            state.grid[rr] = _empty_row(cols)
        if dirty is not None:
            for rr in range(r, rows):
                dirty.add(rr)
    elif event.mode == 1:
        for rr in range(0, r):
            state.grid[rr] = _empty_row(cols)
        for cc in range(0, c + 1):
            state.grid[r][cc] = Cell(" ")
        if dirty is not None:
            for rr in range(0, r + 1):
                dirty.add(rr)
    elif event.mode in (2, 3):
        for rr in range(rows):
            state.grid[rr] = _empty_row(cols)
        if dirty is not None:
            dirty.mark_all()


def _clear_line(
    state: ScreenState, event: ClearLine, dirty: Optional[DirtyRows] = None
) -> None:
    """Clear the current line (or a portion of it) depending on the event mode."""
    cols = state.cols
    r, c = state.cursor_row, state.cursor_col
    if event.mode == 0:
        for cc in range(c, cols):
            state.grid[r][cc] = Cell(" ")
    elif event.mode == 1:
        for cc in range(0, c + 1):
            state.grid[r][cc] = Cell(" ")
    elif event.mode == 2:
        state.grid[r] = _empty_row(cols)
    if dirty is not None:
        dirty.add(r)


def render_as_text(state: ScreenState, trim: bool = True) -> List[str]:
    """Render the grid as a list of strings (mostly for debugging/tests)."""
    lines = []
    for row in state.grid:
        text = "".join(cell.char for cell in row)
        if trim:
            text = text.rstrip(" ")
        lines.append(text)
    return lines


# ════════════════════════════════════════════════════════════════════════════ #
#  DIFF — cell-by-cell screen comparison with scroll detection                #
# ════════════════════════════════════════════════════════════════════════════ #

logger = get_logger("diff")

_SCROLL_MATCH_THRESHOLD = 0.85


def _blank_cell() -> Cell:
    return Cell(char=" ")


def _row_similarity(left: list[Cell], right: list[Cell]) -> float:
    """Calculate the percentage of identical cells between two rows."""
    if not left:
        return 1.0
    matches = sum(1 for a, b in zip(left, right, strict=False) if a == b)
    return matches / len(left)


def _is_blank_row(row: list[Cell]) -> bool:
    """Check if a row consists entirely of blank cells."""
    blank = _blank_cell()
    return all(cell == blank for cell in row)


def _detect_scroll(
    before: ScreenState,
    after: ScreenState,
) -> tuple[bool, str | None, int]:
    """Detect upward/downward scroll by matching shifted row content."""
    if before.rows != after.rows or before.cols != after.cols:
        return False, None, 0

    best_score = 0.0
    best_amount = 0
    best_direction: str | None = None

    for amount in range(1, before.rows):
        up_score = 0.0
        up_rows = 0
        up_non_blank_matches = 0
        for row_idx in range(before.rows - amount):
            left = before.grid[row_idx + amount]
            right = after.grid[row_idx]
            sim = _row_similarity(left, right)
            up_score += sim
            up_rows += 1
            if sim >= _SCROLL_MATCH_THRESHOLD and not _is_blank_row(left):
                up_non_blank_matches += 1
        if up_rows and up_non_blank_matches > 0:
            up_avg = up_score / up_rows
            if up_avg >= _SCROLL_MATCH_THRESHOLD and up_avg > best_score:
                best_score = up_avg
                best_amount = amount
                best_direction = "up"

        down_score = 0.0
        down_rows = 0
        down_non_blank_matches = 0
        for row_idx in range(before.rows - amount):
            left = before.grid[row_idx]
            right = after.grid[row_idx + amount]
            sim = _row_similarity(left, right)
            down_score += sim
            down_rows += 1
            if sim >= _SCROLL_MATCH_THRESHOLD and not _is_blank_row(left):
                down_non_blank_matches += 1
        if down_rows and down_non_blank_matches > 0:
            down_avg = down_score / down_rows
            if down_avg >= _SCROLL_MATCH_THRESHOLD and down_avg > best_score:
                best_score = down_avg
                best_amount = amount
                best_direction = "down"

    if best_amount > 0 and best_direction is not None:
        logger.debug(
            "scroll detected dir=%s amount=%d score=%.3f",
            best_direction, best_amount, best_score,
        )
        return True, best_direction, best_amount
    return False, None, 0


def _compare_cells(
    before: ScreenState,
    after: ScreenState,
    *,
    row_range: range | None = None,
    col_range: range | None = None,
) -> list[CellChange]:
    """Compare two ScreenStates cell by cell and return a list of differences."""
    changes: list[CellChange] = []
    max_r = min(before.rows, after.rows)
    max_c = min(before.cols, after.cols)

    rows = row_range if row_range is not None else range(max_r)
    cols = col_range if col_range is not None else range(max_c)

    for r in rows:
        if r >= max_r:
            continue
        if col_range is None and before.grid[r] == after.grid[r]:
            continue
        for c in cols:
            if c >= max_c:
                continue
            b_cell = before.grid[r][c]
            a_cell = after.grid[r][c]
            if b_cell != a_cell:
                changes.append(CellChange(row=r, col=c, old=b_cell, new=a_cell))
    return changes


def _scroll_change_rows(
    before: ScreenState,
    after: ScreenState,
    direction: str,
    amount: int,
) -> list[CellChange]:
    """Return changes only for rows introduced by a scroll, not shifted content."""
    changes: list[CellChange] = []
    blank = _blank_cell()

    if direction == "up":
        for row in range(before.rows - amount):
            for col in range(before.cols):
                old_cell = before.grid[row + amount][col]
                new_cell = after.grid[row][col]
                if old_cell != new_cell:
                    changes.append(CellChange(row=row, col=col, old=old_cell, new=new_cell))
        for row in range(before.rows - amount, before.rows):
            for col in range(before.cols):
                new_cell = after.grid[row][col]
                if new_cell != blank:
                    changes.append(
                        CellChange(row=row, col=col, old=blank, new=new_cell)
                    )
    elif direction == "down":
        for row in range(amount):
            for col in range(before.cols):
                new_cell = after.grid[row][col]
                if new_cell != blank:
                    changes.append(
                        CellChange(row=row, col=col, old=blank, new=new_cell)
                    )
        for row in range(amount, before.rows):
            for col in range(before.cols):
                old_cell = before.grid[row - amount][col]
                new_cell = after.grid[row][col]
                if old_cell != new_cell:
                    changes.append(CellChange(row=row, col=col, old=old_cell, new=new_cell))
    return changes


def diff_screens(before: ScreenState, after: ScreenState) -> DiffResult:
    """Compare two screen snapshots and report cell-level changes."""
    cursor_moved = (
        before.cursor_row != after.cursor_row or before.cursor_col != after.cursor_col
    )
    new_cursor = (after.cursor_row, after.cursor_col)

    if before.rows != after.rows or before.cols != after.cols:
        changes = _compare_cells(before, after)
        return DiffResult(
            changes=changes,
            cursor_moved=cursor_moved,
            new_cursor=new_cursor,
        )

    scrolled, direction, amount = _detect_scroll(before, after)
    if scrolled and direction is not None and amount > 0:
        changes = _scroll_change_rows(before, after, direction, amount)
        return DiffResult(
            changes=changes,
            cursor_moved=cursor_moved,
            new_cursor=new_cursor,
            scrolled=True,
            scroll_direction=direction,
            scroll_amount=amount,
        )

    changes = _compare_cells(before, after)
    return DiffResult(
        changes=changes,
        cursor_moved=cursor_moved,
        new_cursor=new_cursor,
    )


def diff_screens_incremental(
    before: ScreenState,
    after: ScreenState,
    dirty_rows: Iterable[int],
) -> DiffResult:
    """Incremental fast-path diff over only the rows known to have changed."""
    cursor_moved = (
        before.cursor_row != after.cursor_row or before.cursor_col != after.cursor_col
    )
    new_cursor = (after.cursor_row, after.cursor_col)

    if before.rows != after.rows or before.cols != after.cols:
        changes = _compare_cells(before, after)
    else:
        max_r = min(before.rows, after.rows)
        rows = sorted({r for r in dirty_rows if 0 <= r < max_r})
        changes = _compare_cells(before, after, row_range=rows)

    return DiffResult(
        changes=changes,
        cursor_moved=cursor_moved,
        new_cursor=new_cursor,
    )


_RED = "\x1b[31m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_RESET = "\x1b[0m"


def _colorize(text: str, code: str, enabled: bool) -> str:
    """Wrap ``text`` in an ANSI ``code`` when coloring is enabled."""
    return f"{code}{text}{_RESET}" if enabled else text


def format_diff(diff: DiffResult, *, color: bool = True) -> str:
    """Render a :class:`DiffResult` as a human-readable, git-style block."""
    lines: list[str] = []

    if diff.scrolled:
        lines.append(
            _colorize(
                f"  [Scrolled {diff.scroll_direction} by {diff.scroll_amount} lines]",
                _YELLOW,
                color,
            )
        )

    if diff.cursor_moved:
        lines.append(f"  [Cursor moved to {diff.new_cursor}]")

    for change in diff.changes:
        old_char = change.old.char if change.old.char != " " else "<space>"
        new_char = change.new.char if change.new.char != " " else "<space>"
        old_tok = _colorize(f"{old_char!r}", _RED, color)
        new_tok = _colorize(f"{new_char!r}", _GREEN, color)
        lines.append(
            f"  Row {change.row:02} Col {change.col:02}: {old_tok} -> {new_tok}"
        )

    if not diff.changes and not diff.scrolled and not diff.cursor_moved:
        lines.append("  [No changes detected]")

    return "\n".join(lines)


# ════════════════════════════════════════════════════════════════════════════ #
#  RUNNER — PTY/subprocess command runner                                     #
# ════════════════════════════════════════════════════════════════════════════ #

logger = get_logger("runner")

INTERRUPTED_EXIT_CODE = 130

_FALLBACK_ROWS = 24
_FALLBACK_COLS = 80


def detect_terminal_geometry(
    fallback_rows: int = _FALLBACK_ROWS,
    fallback_cols: int = _FALLBACK_COLS,
) -> tuple[int, int]:
    """Return the current terminal size as ``(rows, cols)``."""
    size = shutil.get_terminal_size(fallback=(fallback_cols, fallback_rows))
    rows = size.lines or fallback_rows
    cols = size.columns or fallback_cols
    return rows, cols


def is_wsl() -> bool:
    """Return True when running under the Windows Subsystem for Linux."""
    if sys.platform != "linux":
        return False
    if os.environ.get("WSL_DISTRO_NAME") or os.environ.get("WSL_INTEROP"):
        return True
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="ignore") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def describe_platform() -> str:
    """Human-readable summary of the terminal backend chosen for this platform."""
    if sys.platform == "win32":
        return "windows: subprocess fallback (no PTY)"
    if is_wsl():
        return "wsl: pty (stdlib)"
    if pty_supported():
        return "unix: pty (stdlib)"
    return "unknown: subprocess fallback"


def pty_supported() -> bool:
    """Return True when the platform can allocate a pseudo-terminal."""
    if sys.platform == "win32":
        return False
    try:
        import pty

        master_fd, slave_fd = pty.openpty()
        os.close(master_fd)
        os.close(slave_fd)
        return True
    except (AttributeError, OSError):
        return False


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    if sys.platform == "win32":
        return
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _read_until_done(
    master_fd: int,
    proc: subprocess.Popen[bytes],
    timeout: float | None,
) -> tuple[bytes, int, bool]:
    """Read PTY output until the process exits or timeout fires."""
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout if timeout is not None else None
    timed_out = False

    while True:
        if deadline is not None and time.monotonic() >= deadline:
            timed_out = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            proc.wait(timeout=2)
            break

        poll_timeout = 0.1 if deadline is not None else None
        try:
            readable, _, _ = select.select([master_fd], [], [], poll_timeout)
        except (OSError, ValueError):
            break

        if master_fd in readable:
            try:
                data = os.read(master_fd, 4096)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    break
                raise
            if not data:
                break
            chunks.append(data)

        if proc.poll() is not None:
            _drain_master(master_fd, chunks)
            break

    exit_code = proc.wait() if proc.poll() is None else proc.returncode
    return b"".join(chunks), exit_code if exit_code is not None else -1, timed_out


def _drain_master(master_fd: int, chunks: list[bytes]) -> None:
    while True:
        try:
            readable, _, _ = select.select([master_fd], [], [], 0)
        except (OSError, ValueError):
            break
        if master_fd not in readable:
            break
        try:
            data = os.read(master_fd, 4096)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)


def _run_single_command_pty(
    command: str,
    command_index: int,
    *,
    timeout: float | None,
    rows: int,
    cols: int,
) -> Generator[RunnerEvent, None, None]:
    import pty

    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, rows, cols)
    _set_winsize(slave_fd, rows, cols)

    proc = subprocess.Popen(
        command,
        shell=True,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    try:
        output, exit_code, timed_out = _read_until_done(master_fd, proc, timeout)
        logger.debug(
            "pty cmd=%r output_bytes=%d exit_code=%s timed_out=%s",
            command, len(output), exit_code, timed_out,
        )
        yield CommandChunk(command=command, data=output, command_index=command_index)
        yield CommandFinished(
            command=command,
            command_index=command_index,
            exit_code=exit_code,
            timed_out=timed_out,
        )
    finally:
        os.close(master_fd)
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            proc.wait(timeout=2)


def _run_single_command_subprocess(
    command: str,
    command_index: int,
    *,
    timeout: float | None,
    rows: int = 24,
    cols: int = 80,
) -> Generator[RunnerEvent, None, None]:
    """Fallback when PTY is unavailable (e.g. Windows dev environments)."""
    logger.debug(
        "subprocess fallback cmd=%r timeout=%s", command, timeout,
    )
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=timeout,
        )
        output = completed.stdout + completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = (exc.stdout or b"") + (exc.stderr or b"")
        exit_code = 124

    yield CommandChunk(command=command, data=output, command_index=command_index)
    yield CommandFinished(
        command=command,
        command_index=command_index,
        exit_code=exit_code,
        timed_out=timed_out,
    )


def run_commands(
    commands: list[str],
    *,
    timeout: float | None = None,
    rows: int | None = None,
    cols: int | None = None,
    use_pty: bool | None = None,
    runner_fn: Callable[..., Generator[RunnerEvent, None, None]] | None = None,
) -> Generator[RunnerEvent, None, None]:
    """Run commands sequentially, yielding output chunks and finish events."""
    if not commands:
        return

    if rows is None or cols is None:
        detected_rows, detected_cols = detect_terminal_geometry()
        rows = detected_rows if rows is None else rows
        cols = detected_cols if cols is None else cols

    use_real_pty = pty_supported() if use_pty is None else use_pty
    single_runner = runner_fn or (
        _run_single_command_pty if use_real_pty else _run_single_command_subprocess
    )
    logger.debug(
        "run_commands count=%d use_pty=%s rows=%s cols=%s timeout=%s",
        len(commands), use_real_pty, rows, cols, timeout,
    )

    for index, command in enumerate(commands):
        try:
            yield from single_runner(
                command,
                index,
                timeout=timeout,
                rows=rows,
                cols=cols,
            )
        except KeyboardInterrupt:
            logger.info(
                "command interrupted cmd=%r (Ctrl-C skip)", command,
            )
            yield CommandChunk(command=command, data=b"", command_index=index)
            yield CommandFinished(
                command=command,
                command_index=index,
                exit_code=INTERRUPTED_EXIT_CODE,
                skipped=True,
            )


# ════════════════════════════════════════════════════════════════════════════ #
#  CONFIG — TOML config + env overrides                                        #
# ════════════════════════════════════════════════════════════════════════════ #

logger = get_logger("config")

try:
    import tomllib
except ModuleNotFoundError:
    tomllib = None

_LOCAL_NAMES = ("config.toml", "termireq.toml")


@dataclass
class TerminalConfig:
    """Virtual/PTY geometry. ``None`` means auto-detect from the real terminal."""
    rows: int | None = None
    cols: int | None = None


@dataclass
class ColorConfig:
    """Diff coloring. ``enabled=None`` means decide automatically."""
    enabled: bool | None = None
    theme: str = "default"


@dataclass
class AccessibilityConfig:
    """Accessibility adapter settings."""
    enabled: bool = False
    backend: str = "auto"
    speech_rate: int | None = None
    stream_path: str | None = None
    verbosity: str = "summary"


@dataclass
class Config:
    """The fully-resolved configuration for a single CLI invocation."""
    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    color: ColorConfig = field(default_factory=ColorConfig)
    accessibility: AccessibilityConfig = field(default_factory=AccessibilityConfig)


def default_config() -> Config:
    """Return a fresh :class:`Config` populated entirely with defaults."""
    return Config()


def _truthy(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def candidate_paths(env: Mapping[str, str] | None = None) -> list[Path]:
    """Return the config file locations to try, in priority order."""
    env = os.environ if env is None else env
    paths: list[Path] = []

    explicit = env.get("TERMIREQ_CONFIG")
    if explicit:
        paths.append(Path(explicit))

    for name in _LOCAL_NAMES:
        paths.append(Path.cwd() / name)

    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    paths.append(base / "termireq" / "config.toml")

    return paths


def _find_config_file(
    path: str | None, env: Mapping[str, str]
) -> Path | None:
    """Resolve which config file to read (or None if there is none)."""
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"config file not found: {path}")
        return p
    for candidate in candidate_paths(env):
        if candidate.is_file():
            return candidate
    return None


def _parse_toml(path: Path) -> dict:
    if tomllib is None:
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _merge_file(config: Config, data: dict) -> None:
    """Overlay parsed TOML ``data`` onto ``config`` in place."""
    term = data.get("terminal", {})
    if isinstance(term, dict):
        if "rows" in term:
            config.terminal.rows = _as_int(term["rows"])
        if "cols" in term:
            config.terminal.cols = _as_int(term["cols"])

    color = data.get("color", {})
    if isinstance(color, dict):
        if "enabled" in color:
            config.color.enabled = bool(color["enabled"])
        if "theme" in color:
            config.color.theme = str(color["theme"])

    a11y = data.get("accessibility", {})
    if isinstance(a11y, dict):
        if "enabled" in a11y:
            config.accessibility.enabled = bool(a11y["enabled"])
        if "backend" in a11y:
            config.accessibility.backend = str(a11y["backend"])
        if "speech_rate" in a11y:
            config.accessibility.speech_rate = _as_int(a11y["speech_rate"])
        if "stream_path" in a11y:
            config.accessibility.stream_path = str(a11y["stream_path"])
        if "verbosity" in a11y:
            config.accessibility.verbosity = str(a11y["verbosity"])


def _apply_env(config: Config, env: Mapping[str, str]) -> None:
    """Layer ``TERMIREQ_*`` (and ``NO_COLOR``) overrides onto ``config``."""
    if "TERMIREQ_ROWS" in env:
        config.terminal.rows = _as_int(env["TERMIREQ_ROWS"])
    if "TERMIREQ_COLS" in env:
        config.terminal.cols = _as_int(env["TERMIREQ_COLS"])
    if env.get("NO_COLOR"):
        config.color.enabled = False
    if "TERMIREQ_COLOR" in env:
        config.color.enabled = _truthy(env["TERMIREQ_COLOR"])
    if env.get("TERMIREQ_THEME"):
        config.color.theme = env["TERMIREQ_THEME"]
    if "TERMIREQ_ACCESSIBILITY" in env:
        config.accessibility.enabled = _truthy(env["TERMIREQ_ACCESSIBILITY"])
    if env.get("TERMIREQ_A11Y_BACKEND"):
        config.accessibility.backend = env["TERMIREQ_A11Y_BACKEND"]
    if "TERMIREQ_SPEECH_RATE" in env:
        config.accessibility.speech_rate = _as_int(env["TERMIREQ_SPEECH_RATE"])
    if env.get("TERMIREQ_A11Y_STREAM"):
        config.accessibility.stream_path = env["TERMIREQ_A11Y_STREAM"]


def load_config(
    path: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Load configuration from ``path`` (or the search path) plus env overrides."""
    env = os.environ if env is None else env
    config = default_config()

    config_file = _find_config_file(path, env)
    if config_file is not None:
        logger.info("loading config from %s", config_file)
        try:
            _merge_file(config, _parse_toml(config_file))
        except (OSError, ValueError):
            logger.warning("could not parse config %s; using defaults", config_file)
    else:
        logger.debug("no config file found; using built-in defaults")

    _apply_env(config, env)
    return config


# ════════════════════════════════════════════════════════════════════════════ #
#  ACCESSIBILITY — zero-dependency adapter layer                              #
# ════════════════════════════════════════════════════════════════════════════ #

logger = get_logger("accessibility")

Runner = Callable[..., None]


class AccessibilityAdapter:
    """Common interface for delivering announcements to assistive technology."""

    available: bool = True

    def announce(self, announcement: AccessibilityAnnouncement) -> None:
        """Deliver a single announcement. Base implementation is a no-op."""

    def announce_all(
        self, announcements: Iterable[AccessibilityAnnouncement]
    ) -> None:
        for announcement in announcements:
            self.announce(announcement)

    def close(self) -> None:
        """Release any resources (files, handles). Safe to call twice."""


class NullAdapter(AccessibilityAdapter):
    """Discards every announcement. Used when accessibility is disabled."""

    available = False


class StreamAdapter(AccessibilityAdapter):
    """Write announcements as plain text lines to a stream or file."""

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        path: str | None = None,
    ) -> None:
        self._owns_stream = False
        if stream is not None:
            self._stream: TextIO = stream
        elif path is not None:
            self._stream = open(path, "a", encoding="utf-8")
            self._owns_stream = True
        else:
            self._stream = sys.stderr

    def announce(self, announcement: AccessibilityAnnouncement) -> None:
        marker = "!" if announcement.priority == "assertive" else ""
        line = f"{marker}[{announcement.kind}] {announcement.text}"
        try:
            self._stream.write(line + "\n")
            self._stream.flush()
        except (ValueError, OSError):
            pass

    def close(self) -> None:
        if self._owns_stream:
            try:
                self._stream.close()
            except OSError:
                pass
            self._owns_stream = False


def _default_runner(cmd: Sequence[str], env: dict | None = None) -> None:
    try:
        subprocess.run(
            list(cmd),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError:
        raise
    except OSError:
        pass


class SpeechAdapter(AccessibilityAdapter):
    """Speak announcements through the operating system's speech service."""

    def __init__(
        self,
        *,
        system: str | None = None,
        speech_rate: int | None = None,
        runner: Callable[..., None] | None = None,
    ) -> None:
        self._system = system or platform.system()
        self._rate = speech_rate
        self._run = runner or _default_runner
        self.available = self._system in ("Darwin", "Linux", "Windows")

    def build_command(
        self, text: str
    ) -> tuple[list[str] | None, dict | None]:
        candidates = self.candidate_commands(text)
        return candidates[0] if candidates else (None, None)

    def candidate_commands(
        self, text: str
    ) -> list[tuple[list[str], dict | None]]:
        if self._system == "Darwin":
            cmd = ["say"]
            if self._rate:
                cmd += ["-r", str(self._rate)]
            cmd.append(text)
            return [(cmd, None)]

        if self._system == "Linux":
            spd = ["spd-say", "-w"]
            espeak = ["espeak"]
            if self._rate:
                spd += ["-r", str(_clamp(self._rate - 175, -100, 100))]
                espeak += ["-s", str(self._rate)]
            spd.append(text)
            espeak.append(text)
            return [(spd, None), (espeak, None)]

        if self._system == "Windows":
            script = (
                "Add-Type -AssemblyName System.Speech;"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "if ($env:TERMIREQ_RATE) { $s.Rate = [int]$env:TERMIREQ_RATE };"
                "$s.Speak($env:TERMIREQ_TEXT)"
            )
            env = dict(os.environ)
            env["TERMIREQ_TEXT"] = text
            if self._rate is not None:
                env["TERMIREQ_RATE"] = str(_clamp((self._rate - 175) // 15, -10, 10))
            return [(["powershell", "-NoProfile", "-Command", script], env)]

        return []

    def announce(self, announcement: AccessibilityAnnouncement) -> None:
        for cmd, env in self.candidate_commands(announcement.text):
            try:
                self._run(cmd, env)
                return
            except FileNotFoundError:
                continue


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


_DESKTOP_SYSTEMS = ("Darwin", "Linux", "Windows")


def get_adapter(
    config: AccessibilityConfig,
    *,
    system: str | None = None,
    stream: TextIO | None = None,
) -> AccessibilityAdapter:
    """Build the adapter described by ``config``."""
    if not config.enabled:
        return NullAdapter()

    sysname = system or platform.system()
    backend = config.backend

    if backend == "auto":
        backend = "speech" if sysname in _DESKTOP_SYSTEMS else "null"

    if backend == "null":
        logger.debug("a11y backend=null")
        return NullAdapter()
    if backend == "stream":
        logger.debug("a11y backend=stream path=%s", config.stream_path)
        return StreamAdapter(stream, path=config.stream_path)
    if backend == "speech":
        logger.debug("a11y backend=speech system=%s rate=%s", sysname, config.speech_rate)
        return SpeechAdapter(system=sysname, speech_rate=config.speech_rate)
    logger.warning("unknown a11y backend %r; using null", backend)
    return NullAdapter()


def _describe_cursor(diff: DiffResult) -> str:
    row, col = diff.new_cursor
    return f"cursor at row {row + 1}, column {col + 1}"


def summarize_diff(
    command: str,
    exit_code: int,
    diff: DiffResult,
    *,
    verbosity: str = "summary",
) -> List[AccessibilityAnnouncement]:
    """Turn a :class:`DiffResult` into ordered accessibility announcements."""
    announcements: List[AccessibilityAnnouncement] = []

    status = "succeeded" if exit_code == 0 else f"failed with exit code {exit_code}"
    n = len(diff.changes)
    parts = [f"Command {command} {status}."]
    if diff.scrolled:
        parts.append(
            f"Screen scrolled {diff.scroll_direction} by {diff.scroll_amount} lines."
        )
    if n == 0 and not diff.scrolled:
        parts.append("No visible changes.")
    else:
        parts.append(f"{n} cell{'s' if n != 1 else ''} changed.")

    announcements.append(
        AccessibilityAnnouncement(
            text=" ".join(parts),
            kind="command_finished",
            priority="polite" if exit_code == 0 else "assertive",
            command=command,
        )
    )

    if verbosity == "detailed" and diff.changes:
        for change in diff.changes:
            old = change.old.char if change.old.char != " " else "blank"
            new = change.new.char if change.new.char != " " else "blank"
            announcements.append(
                AccessibilityAnnouncement(
                    text=(
                        f"Row {change.row + 1} column {change.col + 1}: "
                        f"{old} became {new}."
                    ),
                    kind="cell_change",
                    priority="polite",
                    command=command,
                )
            )

    return announcements


# ════════════════════════════════════════════════════════════════════════════ #
#  CLI — command-line interface (argparse + orchestration)                     #
# ════════════════════════════════════════════════════════════════════════════ #

logger = get_logger("cli")


def create_parser() -> argparse.ArgumentParser:
    """Create and configure the CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="TermiReq: Terminal screen diffing tool."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run commands sequentially and diff their terminal outputs."
    )
    run_parser.add_argument(
        "commands",
        nargs="+",
        help="One or more shell commands to execute"
    )
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Maximum time in seconds to wait for a command to finish"
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Output diff as machine-readable JSON"
    )
    run_parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to a config.toml (overrides the search path)"
    )
    run_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color in the diff output"
    )
    run_parser.add_argument(
        "--accessibility",
        action="store_true",
        help="Emit accessibility announcements of what changed"
    )
    run_parser.add_argument(
        "--a11y-backend",
        choices=["auto", "speech", "stream", "null"],
        default=None,
        help="Accessibility backend to use (implies --accessibility)"
    )
    run_parser.add_argument(
        "--speak",
        action="store_true",
        help="Read the diff out loud (alias for --accessibility --a11y-backend speech)"
    )
    run_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log pipeline steps to stderr at INFO level"
    )
    run_parser.add_argument(
        "--debug",
        action="store_true",
        help="Log per-event detail to stderr at DEBUG level (implies verbose)"
    )

    record_parser = subparsers.add_parser(
        "record",
        help="Run a command and record its raw byte stream to a file."
    )
    record_parser.add_argument(
        "command",
        help="A single shell command to execute and record"
    )
    record_parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path to the binary file where the session will be recorded"
    )
    record_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Maximum time in seconds to wait for a command to finish"
    )
    record_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log pipeline steps to stderr at INFO level"
    )
    record_parser.add_argument(
        "--debug",
        action="store_true",
        help="Log per-event detail to stderr at DEBUG level (implies verbose)"
    )

    replay_parser = subparsers.add_parser(
        "replay",
        help="Replay a recorded terminal byte stream from a file and calculate the diff."
    )
    replay_parser.add_argument(
        "input",
        help="Path to the recorded binary session file"
    )
    replay_parser.add_argument(
        "--json",
        action="store_true",
        help="Output diff as machine-readable JSON"
    )
    replay_parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to a config.toml (overrides the search path)"
    )
    replay_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color in the diff output"
    )
    replay_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log pipeline steps to stderr at INFO level"
    )
    replay_parser.add_argument(
        "--debug",
        action="store_true",
        help="Log per-event detail to stderr at DEBUG level (implies verbose)"
    )

    return parser


def create_empty_state(rows: int, cols: int) -> ScreenState:
    """Create a blank ScreenState for a given terminal geometry."""
    return ScreenState(
        rows=rows,
        cols=cols,
        grid=[[Cell(char=" ") for _ in range(cols)] for _ in range(rows)],
        cursor_row=0,
        cursor_col=0,
    )


def _should_colorize() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def resolve_color(config: Config, *, no_color_flag: bool) -> bool:
    if no_color_flag:
        return False
    if config.color.enabled is not None:
        return config.color.enabled
    return _should_colorize()


def build_config(parsed_args) -> Config:
    """Load config from disk/env, then layer CLI-flag overrides on top."""
    config = load_config(getattr(parsed_args, "config", None))

    if getattr(parsed_args, "speak", False):
        config.accessibility.enabled = True
        config.accessibility.backend = "speech"
    if getattr(parsed_args, "accessibility", False):
        config.accessibility.enabled = True
    if getattr(parsed_args, "a11y_backend", None):
        config.accessibility.enabled = True
        config.accessibility.backend = parsed_args.a11y_backend

    return config


def print_diff(diff_result: DiffResult, *, color: bool = True) -> None:
    """Format and print the diff result to stdout for a human reader."""
    print(format_diff(diff_result, color=color))


def main(args: List[str] | None = None) -> int:
    """Main CLI execution flow."""
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.subcommand == "run":
        root_logger = configure_logging(
            verbose=parsed_args.verbose,
            debug=parsed_args.debug,
        )
        root_logger.debug(
            "CLI args=%s verbose=%s debug=%s", parsed_args, parsed_args.verbose, parsed_args.debug
        )

        config = build_config(parsed_args)

        detected_rows, detected_cols = detect_terminal_geometry()
        rows = config.terminal.rows or detected_rows
        cols = config.terminal.cols or detected_cols
        root_logger.debug(
            "geometry detected=%s config=%s using=%s",
            (detected_rows, detected_cols),
            (config.terminal.rows, config.terminal.cols),
            (rows, cols),
        )

        use_color = resolve_color(config, no_color_flag=parsed_args.no_color)
        root_logger.debug(
            "color_enabled=%s (no_color_flag=%s, config=%s, stdout_tty=%s)",
            use_color, parsed_args.no_color, config.color.enabled, sys.stdout.isatty(),
        )

        adapter = get_adapter(config.accessibility)
        observer = adapter.announce if adapter.available else None
        verbosity = config.accessibility.verbosity
        root_logger.info(
            "platform=%s a11y_backend=%s observer=%s",
            describe_platform(),
            config.accessibility.backend,
            "active" if observer is not None else "inactive",
        )

        runner_events = run_commands(parsed_args.commands, timeout=parsed_args.timeout, rows=rows, cols=cols)

        current_state = create_empty_state(rows, cols)
        before_state = current_state.snapshot()
        ansi_parser = ANSIParser()
        root_logger.debug(
            "pipeline ready screen=%dx%d parser=%s", rows, cols, type(ansi_parser).__name__
        )

        try:
            for event in runner_events:
                if isinstance(event, CommandChunk):
                    root_logger.debug(
                        "CommandChunk cmd=%r bytes=%d",
                        event.command, len(event.data),
                    )
                    apply_events(
                        current_state,
                        ansi_parser.feed(event.data),
                        observer=observer,
                    )

                elif isinstance(event, CommandFinished):
                    after_state = current_state.snapshot()
                    diff_result = diff_screens(before_state, after_state)
                    root_logger.info(
                        "command_finished cmd=%r exit_code=%s changes=%d scrolled=%s",
                        event.command, event.exit_code, len(diff_result.changes),
                        diff_result.scrolled,
                    )

                    if parsed_args.json:
                        data = {
                            "command": event.command,
                            "exit_code": event.exit_code,
                            "diff": dataclasses.asdict(diff_result)
                        }
                        print(json.dumps(data, indent=2))
                    else:
                        print(f"--- Command '{event.command}' finished (exit code {event.exit_code}) ---")
                        print_diff(diff_result, color=use_color)

                    if adapter.available:
                        adapter.announce_all(
                            summarize_diff(
                                event.command,
                                event.exit_code,
                                diff_result,
                                verbosity=verbosity,
                            )
                        )

                    current_state = create_empty_state(rows, cols)
                    before_state = current_state.snapshot()
                    ansi_parser = ANSIParser()
        finally:
            adapter.close()

        return 0

    elif parsed_args.subcommand == "record":
        root_logger = configure_logging(verbose=parsed_args.verbose, debug=parsed_args.debug)
        config = build_config(parsed_args)
        detected_rows, detected_cols = detect_terminal_geometry()
        rows = config.terminal.rows or detected_rows
        cols = config.terminal.cols or detected_cols
        runner_events = run_commands([parsed_args.command], timeout=parsed_args.timeout, rows=rows, cols=cols)

        with open(parsed_args.output, "wb") as f:
            for event in runner_events:
                if isinstance(event, CommandChunk):
                    f.write(event.data)
                elif isinstance(event, CommandFinished):
                    print(f"--- Command '{event.command}' recorded (exit code {event.exit_code}) ---")
        return 0

    elif parsed_args.subcommand == "replay":
        root_logger = configure_logging(verbose=parsed_args.verbose, debug=parsed_args.debug)
        config = build_config(parsed_args)

        detected_rows, detected_cols = detect_terminal_geometry()
        rows = config.terminal.rows or detected_rows
        cols = config.terminal.cols or detected_cols
        use_color = resolve_color(config, no_color_flag=parsed_args.no_color)

        adapter = get_adapter(config.accessibility)
        observer = adapter.announce if adapter.available else None
        verbosity = config.accessibility.verbosity

        try:
            with open(parsed_args.input, "rb") as f:
                data = f.read()

            current_state = create_empty_state(rows, cols)
            before_state = current_state.snapshot()
            ansi_parser = ANSIParser()

            apply_events(current_state, ansi_parser.feed(data), observer=observer)

            diff_result = diff_screens(before_state, current_state)
            if parsed_args.json:
                out_data = {
                    "command": f"replay {parsed_args.input}",
                    "exit_code": 0,
                    "diff": dataclasses.asdict(diff_result)
                }
                print(json.dumps(out_data, indent=2))
            else:
                print(f"--- Replay '{parsed_args.input}' finished ---")
                print_diff(diff_result, color=use_color)

            if adapter.available:
                adapter.announce_all(
                    summarize_diff(
                        f"replay {parsed_args.input}",
                        0,
                        diff_result,
                        verbosity=verbosity,
                    )
                )
        finally:
            adapter.close()

        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())

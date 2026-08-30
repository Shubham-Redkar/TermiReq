"""Shared data contract (T0) for parser, screen, diff, and runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


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


ParserEvent = Union[
    PrintChar,
    MoveCursor,
    ClearScreen,
    ClearLine,
    SetStyle,
    SaveCursor,
    RestoreCursor,
    SetTitle,
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
        return ScreenState(
            rows=self.rows,
            cols=self.cols,
            grid=[
                [Cell(char=cell.char, style=cell.style) for cell in row]
                for row in self.grid
            ],
            cursor_row=self.cursor_row,
            cursor_col=self.cursor_col,
            title=self.title,
        )



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
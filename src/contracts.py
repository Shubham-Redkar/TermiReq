"""Shared data contract (T0) for parser, screen, diff, and runner."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass(frozen=True)
class Style:
    fg_color: str | None = None
    bg_color: str | None = None
    bold: bool = False


@dataclass
class Cell:
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
    UnknownSequence,
]


@dataclass
class ScreenState:
    rows: int
    cols: int
    grid: list[list[Cell]]
    cursor_row: int
    cursor_col: int

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
        )


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
    scrolled: bool = False
    scroll_direction: str | None = None
    scroll_amount: int = 0


@dataclass
class CommandChunk:
    command: str
    data: bytes
    command_index: int


@dataclass
class CommandFinished:
    command: str
    command_index: int
    exit_code: int
    timed_out: bool = False
    skipped: bool = False


RunnerEvent = Union[CommandChunk, CommandFinished]

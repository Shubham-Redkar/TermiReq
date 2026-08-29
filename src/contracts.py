"""shared data contract (T0)."""

from dataclasses import dataclass, field
from typing import Union
from collections.abc import Generator

# --- 1. Shared basics ---

@dataclass(frozen=True)
class Style:
    fg_color: str | None = None   # e.g. "red", "green"
    bg_color: str | None = None
    bold: bool = False

@dataclass
class Cell:
    char: str              # single character; " " (space) means empty
    style: Style = field(default_factory=Style)


# --- 2. Parser Events ---

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

ParserEvent = Union[
    PrintChar, MoveCursor, ClearScreen, ClearLine,
    SetStyle, SaveCursor, RestoreCursor, UnknownSequence
]


# --- 3. Screen State ---

@dataclass
class ScreenState:
    rows: int
    cols: int
    grid: list[list[Cell]]     # grid[row][col]
    cursor_row: int
    cursor_col: int

    def snapshot(self) -> "ScreenState":
        # Deep copy to allow before/after diffing
        new_grid = [
            [Cell(char=cell.char, style=cell.style) for cell in row]
            for row in self.grid
        ]
        return ScreenState(
            rows=self.rows,
            cols=self.cols,
            grid=new_grid,
            cursor_row=self.cursor_row,
            cursor_col=self.cursor_col
        )


# --- 4. Diff Output ---

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
    # scroll detection cut per Day 1 scope


# --- 5. Runner Events ---

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

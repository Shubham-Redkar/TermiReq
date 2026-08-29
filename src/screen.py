"""Virtual screen grid (T3).

Consumes parser events and maintains a 2D grid of cells, tracking the cursor
position and per-cell character + style. Mutates the :class:`ScreenState` in
place (per the T0 decision); call :meth:`ScreenState.snapshot` before any diff
comparison.

Design decisions baked in (see docs/ttydiff-t0-contract.md):
    - ``apply_event(state, event)`` mutates ``state`` in place and returns None.
    - ``ScreenState.snapshot()`` is a real deep copy (non-negotiable for diffing).
    - The screen resets to blank between commands (a documented limitation).
    - The parser embeds the active style into each ``PrintChar`` event, so the
      screen stores the full cell (char + style) and does not need to track
      ``SetStyle`` itself — it only applies the style that came with the char.
    - Cursor movement clamps to the grid bounds.
    - A newline moves the cursor down one line; tabs advance to the next tab
      stop (every 8 columns).
"""

from __future__ import annotations

import unicodedata
import unicodedata
from typing import List, Optional

from .contracts import (
    Cell, ClearLine, ClearScreen, MoveCursor, PrintChar, RestoreCursor,
    SaveCursor, ScreenState, SetStyle, SetTitle, Style,
)


TAB_STOP = 8


def _empty_row(cols: int) -> List[Cell]:
    return [Cell(" ") for _ in range(cols)]


def apply_event(state: ScreenState, event) -> None:
    """Apply a single parser event to ``state`` in place."""
    if isinstance(event, PrintChar):
        _print_char(state, event)
    elif isinstance(event, MoveCursor):
        _move_cursor(state, event)
    elif isinstance(event, ClearScreen):
        _clear_screen(state, event)
    elif isinstance(event, ClearLine):
        _clear_line(state, event)
    elif isinstance(event, SaveCursor):
        state.__dict__["_saved_cursor"] = (state.cursor_row, state.cursor_col)
    elif isinstance(event, RestoreCursor):
        saved = state.__dict__.get("_saved_cursor")
        if saved is not None:
            state.cursor_row, state.cursor_col = saved
    elif isinstance(event, SetStyle):
        # The parser bakes style into each PrintChar; nothing to do here.
        return
    elif isinstance(event, SetTitle):
        state.title = event.title
    # UnknownSequence and anything unrecognized: ignore (the parser already
    # emitted a diagnostic; we must never crash the pipeline).


def apply_events(state: ScreenState, events) -> None:
    """Apply a sequence of events to ``state`` in place."""
    for event in events:
        apply_event(state, event)


# --------------------------------------------------------------------------- #
# Event handlers
# --------------------------------------------------------------------------- #

def _print_char(state: ScreenState, event: PrintChar) -> None:
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
        return

    if 0 <= row < rows and 0 <= col < cols:
        state.grid[row][col] = Cell(event.char, event.style)
        
        # Calculate display width: 'W' (Wide) and 'F' (Fullwidth) take 2 columns
        width = 0
        for ch in event.char:
            eaw = unicodedata.east_asian_width(ch)
            width += 2 if eaw in ('W', 'F') else 1
        
        # Advance cursor by width, wrapping off the right edge.
        if col + width < cols:
            state.cursor_col += width
        elif row + 1 < rows:
            state.cursor_row += 1
            state.cursor_col = 0
        else:
            state.grid.pop(0)
            state.grid.append(_empty_row(cols))
            state.cursor_col = 0


def _move_cursor(state: ScreenState, event: MoveCursor) -> None:
    rows, cols = state.rows, state.cols
    if event.absolute:
        state.cursor_row = max(0, min(rows - 1, event.row))
        state.cursor_col = max(0, min(cols - 1, event.col))
        return
    # Relative move. Down is +row, up is -row (parser signs them).
    new_row = max(0, min(rows - 1, state.cursor_row + event.row))
    new_col = max(0, min(cols - 1, state.cursor_col + event.col))
    state.cursor_row = new_row
    state.cursor_col = new_col


def _clear_screen(state: ScreenState, event: ClearScreen) -> None:
    rows, cols = state.rows, state.cols
    r, c = state.cursor_row, state.cursor_col
    if event.mode == 0:               # cursor -> end of screen
        for cc in range(c, cols):
            state.grid[r][cc] = Cell(" ")
        for rr in range(r + 1, rows):
            state.grid[rr] = _empty_row(cols)
    elif event.mode == 1:             # start of screen -> cursor
        for rr in range(0, r):
            state.grid[rr] = _empty_row(cols)
        for cc in range(0, c + 1):
            state.grid[r][cc] = Cell(" ")
    elif event.mode in (2, 3):        # whole screen (3 == 2 for most terminals)
        for rr in range(rows):
            state.grid[rr] = _empty_row(cols)


def _clear_line(state: ScreenState, event: ClearLine) -> None:
    cols = state.cols
    r, c = state.cursor_row, state.cursor_col
    if event.mode == 0:               # cursor -> end of line
        for cc in range(c, cols):
            state.grid[r][cc] = Cell(" ")
    elif event.mode == 1:             # start of line -> cursor
        for cc in range(0, c + 1):
            state.grid[r][cc] = Cell(" ")
    elif event.mode == 2:             # whole line
        state.grid[r] = _empty_row(cols)


def render_as_text(state: ScreenState, trim: bool = True) -> List[str]:
    """Render the grid as a list of strings (mostly for debugging/tests)."""
    lines = []
    for row in state.grid:
        text = "".join(cell.char for cell in row)
        if trim:
            text = text.rstrip(" ")
        lines.append(text)
    return lines

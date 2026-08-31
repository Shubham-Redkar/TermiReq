"""Virtual screen grid.

Consumes parser events and maintains a 2D grid of cells, tracking the cursor
position and per-cell character + style. Mutates the :class:`ScreenState` in
place; call :meth:`ScreenState.snapshot` before any diff
comparison.

Design decisions baked in:
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
from typing import Callable, List, Optional

from .contracts import (
    AccessibilityAnnouncement, Cell, ClearLine, ClearScreen, MoveCursor,
    PrintChar, RestoreCursor, SaveCursor, ScreenState, SetStyle, SetTitle, Style,
    SwitchToAlternateScreen, SwitchToMainScreen,
)
from .logger import get_logger

logger = get_logger(__name__)


TAB_STOP = 8

# An observer is notified of screen-level events worth surfacing to assistive
# technology (title changes, full-screen clears). It is optional: when None,
# ``apply_event`` behaves exactly as before, so existing call sites and the
# pure diffing pipeline are unaffected.
Observer = Callable[[AccessibilityAnnouncement], None]


class DirtyRows:
    """Tracks which grid rows changed, for incremental diffing (Task 3).

    Feeding this into :func:`apply_events` lets a caller later diff only the
    rows that actually mutated instead of scanning the whole grid and running
    O(rows^2) scroll detection. When a scroll occurs every row shifts, so the
    tracker flips to :attr:`all` and the caller should fall back to a full diff
    (which is what detects the scroll).
    """

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
        """Return the changed row indices within ``[0, total)``, sorted."""
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
    """Apply a single parser event to ``state`` in place.

    When ``observer`` is given, screen-level accessibility notifications (title
    set, screen cleared) are emitted to it as :class:`AccessibilityAnnouncement`
    objects. When ``dirty`` is given, the rows this event mutates are recorded
    on it for later incremental diffing. Neither argument changes the grid
    mutation, so existing call sites are unaffected.
    """
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
        # The parser bakes style into each PrintChar; nothing to do here.
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
    # UnknownSequence and anything unrecognized: ignore (the parser already
    # emitted a diagnostic; we must never crash the pipeline).


def apply_events(
    state: ScreenState,
    events,
    observer: Optional[Observer] = None,
    dirty: Optional[DirtyRows] = None,
) -> None:
    """Apply a sequence of events to ``state`` in place."""
    for event in events:
        apply_event(state, event, observer, dirty)


# --------------------------------------------------------------------------- #
# Event handlers
# --------------------------------------------------------------------------- #

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
                dirty.mark_all()  # a scroll shifts every row
        return

    if 0 <= row < rows and 0 <= col < cols:
        state.grid[row][col] = Cell(event.char, event.style)
        if dirty is not None:
            dirty.add(row)

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
            if dirty is not None:
                dirty.mark_all()  # bottom-edge wrap scrolled the grid


def _move_cursor(state: ScreenState, event: MoveCursor) -> None:
    """Move the cursor absolutely or relatively, clamping to screen boundaries."""
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


def _clear_screen(
    state: ScreenState, event: ClearScreen, dirty: Optional[DirtyRows] = None
) -> None:
    """Clear the screen (or a portion of it) depending on the event mode."""
    rows, cols = state.rows, state.cols
    r, c = state.cursor_row, state.cursor_col
    if event.mode == 0:               # cursor -> end of screen
        for cc in range(c, cols):
            state.grid[r][cc] = Cell(" ")
        for rr in range(r + 1, rows):
            state.grid[rr] = _empty_row(cols)
        if dirty is not None:
            for rr in range(r, rows):
                dirty.add(rr)
    elif event.mode == 1:             # start of screen -> cursor
        for rr in range(0, r):
            state.grid[rr] = _empty_row(cols)
        for cc in range(0, c + 1):
            state.grid[r][cc] = Cell(" ")
        if dirty is not None:
            for rr in range(0, r + 1):
                dirty.add(rr)
    elif event.mode in (2, 3):        # whole screen (3 == 2 for most terminals)
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
    if event.mode == 0:               # cursor -> end of line
        for cc in range(c, cols):
            state.grid[r][cc] = Cell(" ")
    elif event.mode == 1:             # start of line -> cursor
        for cc in range(0, c + 1):
            state.grid[r][cc] = Cell(" ")
    elif event.mode == 2:             # whole line
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

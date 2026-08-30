"""Diff engine (T4): cell-by-cell screen comparison with scroll detection."""

from __future__ import annotations

from src.contracts import Cell, CellChange, DiffResult, ScreenState

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
        # Check shifted rows for any modifications that happened alongside the scroll
        for row in range(before.rows - amount):
            for col in range(before.cols):
                old_cell = before.grid[row + amount][col]
                new_cell = after.grid[row][col]
                if old_cell != new_cell:
                    changes.append(CellChange(row=row, col=col, old=old_cell, new=new_cell))

        # Check newly exposed rows at the bottom
        for row in range(before.rows - amount, before.rows):
            for col in range(before.cols):
                new_cell = after.grid[row][col]
                if new_cell != blank:
                    changes.append(
                        CellChange(row=row, col=col, old=blank, new=new_cell)
                    )
    elif direction == "down":
        # Check newly exposed rows at the top
        for row in range(amount):
            for col in range(before.cols):
                new_cell = after.grid[row][col]
                if new_cell != blank:
                    changes.append(
                        CellChange(row=row, col=col, old=blank, new=new_cell)
                    )

        # Check shifted rows for any modifications
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


# --------------------------------------------------------------------------- #
# Human-readable formatting (git-style, ANSI-colored)
# --------------------------------------------------------------------------- #

# Raw ANSI color codes. Kept here (not in the CLI) so the diff layer owns the
# full "render a DiffResult for a human" concern; the CLI just prints the
# result and decides whether color is appropriate for the current output.
_RED = "\x1b[31m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_RESET = "\x1b[0m"


def _colorize(text: str, code: str, enabled: bool) -> str:
    """Wrap ``text`` in an ANSI ``code`` when coloring is enabled."""
    return f"{code}{text}{_RESET}" if enabled else text


def format_diff(diff: DiffResult, *, color: bool = True) -> str:
    """Render a :class:`DiffResult` as a human-readable, git-style block.

    Old cell contents are shown in red, new contents in green, and scroll
    reports in yellow. Pass ``color=False`` to emit plain text — the CLI passes
    this flag based on ``NO_COLOR`` and whether stdout is a real terminal, so
    raw escape codes never leak into pipes or files.
    """
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
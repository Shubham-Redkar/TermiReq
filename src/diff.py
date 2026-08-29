"""Diff engine (T4): cell-by-cell screen comparison with scroll detection."""

from __future__ import annotations

from src.contracts import Cell, CellChange, DiffResult, ScreenState

_SCROLL_MATCH_THRESHOLD = 0.85


def _blank_cell() -> Cell:
    return Cell(char=" ")


def _row_similarity(left: list[Cell], right: list[Cell]) -> float:
    if not left:
        return 1.0
    matches = sum(1 for a, b in zip(left, right, strict=False) if a == b)
    return matches / len(left)


def _is_blank_row(row: list[Cell]) -> bool:
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
    rows = row_range if row_range is not None else range(before.rows)
    cols = col_range if col_range is not None else range(before.cols)
    changes: list[CellChange] = []

    for row in rows:
        for col in cols:
            old_cell = before.grid[row][col]
            new_cell = after.grid[row][col]
            if old_cell != new_cell:
                changes.append(
                    CellChange(row=row, col=col, old=old_cell, new=new_cell)
                )
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

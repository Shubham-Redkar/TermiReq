"""Unit tests for the diff engine (T4)."""

import unittest

from src.contracts import Cell, CellChange, DiffResult, ScreenState, Style
from src.diff import diff_screens, diff_screens_incremental, format_diff
from src.screen import DirtyRows, apply_events
from src.parser import ANSIParser


def _make_screen(
    rows: int,
    cols: int,
    lines: list[str],
    *,
    cursor_row: int = 0,
    cursor_col: int = 0,
) -> ScreenState:
    grid: list[list[Cell]] = []
    for row_idx in range(rows):
        row_cells: list[Cell] = []
        line = lines[row_idx] if row_idx < len(lines) else ""
        for col_idx in range(cols):
            char = line[col_idx] if col_idx < len(line) else " "
            row_cells.append(Cell(char=char))
        grid.append(row_cells)
    return ScreenState(
        rows=rows,
        cols=cols,
        grid=grid,
        cursor_row=cursor_row,
        cursor_col=cursor_col,
    )


class TestDiffScreens(unittest.TestCase):
    def test_identical_screens_have_no_changes(self) -> None:
        before = _make_screen(2, 5, ["hello", "world"])
        after = before.snapshot()
        result = diff_screens(before, after)
        self.assertEqual(result.changes, [])
        self.assertFalse(result.cursor_moved)
        self.assertFalse(result.scrolled)

    def test_single_cell_change(self) -> None:
        before = _make_screen(1, 5, ["hello"])
        after = _make_screen(1, 5, ["hallo"])
        result = diff_screens(before, after)
        self.assertEqual(len(result.changes), 1)
        self.assertEqual(result.changes[0].row, 0)
        self.assertEqual(result.changes[0].col, 1)
        self.assertEqual(result.changes[0].old.char, "e")
        self.assertEqual(result.changes[0].new.char, "a")

    def test_style_only_change(self) -> None:
        green = Style(fg_color="green")
        before = _make_screen(1, 3, ["abc"])
        after = ScreenState(
            rows=1,
            cols=3,
            grid=[
                [
                    Cell(char="a"),
                    Cell(char="b", style=green),
                    Cell(char="c"),
                ]
            ],
            cursor_row=0,
            cursor_col=0,
        )
        result = diff_screens(before, after)
        self.assertEqual(len(result.changes), 1)
        self.assertEqual(result.changes[0].col, 1)
        self.assertEqual(result.changes[0].new.style.fg_color, "green")

    def test_cursor_move_without_content_change(self) -> None:
        before = _make_screen(2, 3, ["abc", "   "], cursor_row=0, cursor_col=0)
        after = _make_screen(2, 3, ["abc", "   "], cursor_row=1, cursor_col=2)
        result = diff_screens(before, after)
        self.assertEqual(result.changes, [])
        self.assertTrue(result.cursor_moved)
        self.assertEqual(result.new_cursor, (1, 2))

    def test_scroll_up_detection(self) -> None:
        before = _make_screen(
            4,
            4,
            [
                "line",
                "two ",
                "thre",
                "four",
            ],
        )
        after = _make_screen(
            4,
            4,
            [
                "two ",
                "thre",
                "four",
                "new!",
            ],
        )
        result = diff_screens(before, after)
        self.assertTrue(result.scrolled)
        self.assertEqual(result.scroll_direction, "up")
        self.assertEqual(result.scroll_amount, 1)
        changed_chars = {(c.row, c.col, c.new.char) for c in result.changes}
        self.assertIn((3, 0, "n"), changed_chars)

    def test_scroll_down_detection(self) -> None:
        before = _make_screen(
            4,
            4,
            [
                "aaaa",
                "bbbb",
                "cccc",
                "dddd",
            ],
        )
        after = _make_screen(
            4,
            4,
            [
                "new!",
                "aaaa",
                "bbbb",
                "cccc",
            ],
        )
        result = diff_screens(before, after)
        self.assertTrue(result.scrolled)
        self.assertEqual(result.scroll_direction, "down")
        self.assertEqual(result.scroll_amount, 1)

    def test_snapshot_isolation(self) -> None:
        before = _make_screen(1, 3, ["abc"])
        after = before.snapshot()
        after.grid[0][0] = Cell(char="x")
        result = diff_screens(before, after)
        self.assertEqual(len(result.changes), 1)


_RED = "\x1b[31m"
_GREEN = "\x1b[32m"
_YELLOW = "\x1b[33m"
_RESET = "\x1b[0m"


class TestFormatDiff(unittest.TestCase):
    def _one_change_diff(self) -> DiffResult:
        return DiffResult(
            changes=[
                CellChange(row=0, col=1, old=Cell(char="e"), new=Cell(char="a"))
            ],
            cursor_moved=False,
            new_cursor=(0, 0),
        )

    def test_plain_output_has_no_ansi_codes(self) -> None:
        out = format_diff(self._one_change_diff(), color=False)
        self.assertNotIn("\x1b[", out)
        self.assertIn("Row 00 Col 01: 'e' -> 'a'", out)

    def test_colored_output_wraps_old_red_and_new_green(self) -> None:
        out = format_diff(self._one_change_diff(), color=True)
        self.assertIn(f"{_RED}'e'{_RESET}", out)
        self.assertIn(f"{_GREEN}'a'{_RESET}", out)

    def test_scroll_report_is_yellow(self) -> None:
        diff = DiffResult(
            changes=[],
            cursor_moved=False,
            new_cursor=(0, 0),
            scrolled=True,
            scroll_direction="up",
            scroll_amount=2,
        )
        out = format_diff(diff, color=True)
        self.assertIn(f"{_YELLOW}  [Scrolled up by 2 lines]{_RESET}", out)

    def test_no_changes_message(self) -> None:
        diff = DiffResult(changes=[], cursor_moved=False, new_cursor=(0, 0))
        self.assertEqual(format_diff(diff, color=False), "  [No changes detected]")

    def test_blank_cells_render_as_space_token(self) -> None:
        diff = DiffResult(
            changes=[
                CellChange(row=1, col=2, old=Cell(char="x"), new=Cell(char=" "))
            ],
            cursor_moved=False,
            new_cursor=(0, 0),
        )
        out = format_diff(diff, color=False)
        self.assertIn("'x' -> '<space>'", out)

    def test_cursor_move_line_present(self) -> None:
        diff = DiffResult(changes=[], cursor_moved=True, new_cursor=(3, 7))
        out = format_diff(diff, color=False)
        self.assertIn("[Cursor moved to (3, 7)]", out)
        self.assertNotIn("No changes detected", out)


class TestIncrementalDiff(unittest.TestCase):
    """diff_screens_incremental must match the full diff on non-scroll edits."""

    def test_matches_full_diff_for_single_row(self) -> None:
        before = _make_screen(4, 5, ["aaaaa", "bbbbb", "ccccc", "ddddd"])
        after = _make_screen(4, 5, ["aaaaa", "bXbbb", "ccccc", "ddddd"])
        full = diff_screens(before, after)
        incr = diff_screens_incremental(before, after, [1])
        self.assertEqual(incr.changes, full.changes)

    def test_superset_of_dirty_rows_is_safe(self) -> None:
        before = _make_screen(4, 5, ["aaaaa", "bbbbb", "ccccc", "ddddd"])
        after = _make_screen(4, 5, ["aaaaa", "bXbbb", "ccccc", "ddddd"])
        # Passing extra (clean) rows still yields exactly the real change.
        incr = diff_screens_incremental(before, after, [0, 1, 2, 3])
        self.assertEqual(len(incr.changes), 1)
        self.assertEqual(incr.changes[0].row, 1)

    def test_out_of_range_rows_ignored(self) -> None:
        before = _make_screen(2, 3, ["abc", "def"])
        after = before.snapshot()
        incr = diff_screens_incremental(before, after, [5, -1, 99])
        self.assertEqual(incr.changes, [])

    def test_tracks_cursor(self) -> None:
        before = _make_screen(2, 3, ["abc", "def"], cursor_row=0, cursor_col=0)
        after = _make_screen(2, 3, ["abc", "def"], cursor_row=1, cursor_col=2)
        incr = diff_screens_incremental(before, after, [])
        self.assertTrue(incr.cursor_moved)
        self.assertEqual(incr.new_cursor, (1, 2))

    def test_dirty_tracker_end_to_end(self) -> None:
        # Apply real parser output while tracking dirty rows, then confirm the
        # incremental diff equals the full diff.
        before = ScreenState.blank(6, 20)
        after = before.snapshot()
        dirty = DirtyRows()
        parser = ANSIParser()
        # Move to row 3 (CUP is 1-based) and write text -> only that row dirties.
        apply_events(after, parser.parse(b"\x1b[4;1HHello"), dirty=dirty)
        self.assertFalse(dirty.all)
        self.assertEqual(dirty.rows(after.rows), [3])
        full = diff_screens(before, after)
        incr = diff_screens_incremental(before, after, dirty.rows(after.rows))
        self.assertEqual(incr.changes, full.changes)


if __name__ == "__main__":
    unittest.main()

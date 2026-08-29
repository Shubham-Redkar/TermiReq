"""Unit tests for the diff engine (T4)."""

import unittest

from src.contracts import Cell, ScreenState, Style
from src.diff import diff_screens


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


if __name__ == "__main__":
    unittest.main()

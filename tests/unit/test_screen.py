"""unit tests for virtual screen (T3) + wide chars + SetTitle."""

from __future__ import annotations
import unittest
from src.contracts import (
    Cell, ClearLine, ClearScreen, MoveCursor, PrintChar, SaveCursor,
    RestoreCursor, ScreenState, SetStyle, SetTitle, Style,
)
from src.screen import apply_event, render_as_text
from src.parser import ANSIParser


def blank(rows=3, cols=10):
    return ScreenState.blank(rows, cols)


def print_char(state, ch, style=None):
    apply_event(state, PrintChar(ch, style or Style(), 0))


class TestPrinting(unittest.TestCase):
    def test_print_at_cursor(self):
        s = blank()
        print_char(s, "H")
        self.assertEqual(s.grid[0][0].char, "H")
        self.assertEqual((s.cursor_row, s.cursor_col), (0, 1))

    def test_print_advances(self):
        s = blank()
        print_char(s, "a")
        print_char(s, "b")
        self.assertEqual(render_as_text(s)[0], "ab")

    def test_wraps_at_right_edge(self):
        s = blank(rows=2, cols=3)
        for ch in "abcd":
            print_char(s, ch)
        self.assertEqual(render_as_text(s)[0], "abc")
        self.assertEqual(render_as_text(s)[1], "d")
        self.assertEqual((s.cursor_row, s.cursor_col), (1, 1))

    def test_tab_advances(self):
        s = blank(cols=20)
        print_char(s, "a")
        print_char(s, "\t")
        self.assertEqual(s.cursor_col, 8)

    def test_newline(self):
        s = blank()
        print_char(s, "\n")
        self.assertEqual(s.cursor_row, 1)

    def test_carriage_return(self):
        s = blank()
        print_char(s, "abc")
        print_char(s, "\r")
        self.assertEqual(s.cursor_col, 0)


class TestWideChar(unittest.TestCase):
    def test_emoji_takes_two_cols(self):
        s = blank(cols=10)
        print_char(s, "\U0001f600")  # grinning face
        self.assertEqual((s.cursor_row, s.cursor_col), (0, 2))

    def test_cjk_takes_two_cols(self):
        s = blank(cols=10)
        print_char(s, "\u4e2d")  # 中
        self.assertEqual((s.cursor_row, s.cursor_col), (0, 2))

    def test_ascii_takes_one_col(self):
        s = blank(cols=10)
        print_char(s, "A")
        self.assertEqual((s.cursor_row, s.cursor_col), (0, 1))

    def test_mixed_width_string(self):
        s = blank(cols=20)
        for ch in "A\u4e2dB":
            print_char(s, ch)
        # A at 0, 中 at 1-2, B at 3
        self.assertEqual(s.cursor_col, 4)

    def test_wide_char_wraps(self):
        s = blank(rows=2, cols=3)
        # Fill first 2 cols, then wide char should wrap to next row
        print_char(s, "x")
        print_char(s, "\u4e2d")  # takes cols 1-2
        print_char(s, "y")       # wraps to row 1
        self.assertEqual((s.cursor_row, s.cursor_col), (1, 1))
        self.assertEqual(s.grid[0][0].char, "x")
        self.assertEqual(s.grid[0][1].char, "\u4e2d")
        self.assertEqual(s.grid[1][0].char, "y")


class TestCursorMovement(unittest.TestCase):
    def test_absolute(self):
        s = blank()
        apply_event(s, MoveCursor(2, 3, True, 0))
        self.assertEqual((s.cursor_row, s.cursor_col), (2, 3))

    def test_relative_up(self):
        s = blank()
        apply_event(s, MoveCursor(1, 0, True, 0))
        apply_event(s, MoveCursor(-1, 0, False, 0))
        self.assertEqual(s.cursor_row, 0)

    def test_clamps(self):
        s = blank(rows=3, cols=5)
        apply_event(s, MoveCursor(-99, 99, True, 0))
        self.assertEqual((s.cursor_row, s.cursor_col), (0, 4))


class TestErase(unittest.TestCase):
    def test_clear_line_end(self):
        s = blank(cols=6)
        for ch in "abcdef":
            print_char(s, ch)
        apply_event(s, MoveCursor(0, 0, True, 0))
        apply_event(s, ClearLine(0, 0))
        self.assertEqual(render_as_text(s, trim=False)[0], "      ")

    def test_clear_screen_all(self):
        s = blank(rows=3, cols=5)
        for ch in "hello":
            print_char(s, ch)
        apply_event(s, ClearScreen(2, 0))
        for row in s.grid:
            self.assertTrue(all(c.char == " " for c in row))


class TestSetTitle(unittest.TestCase):
    def test_title_from_osc(self):
        s = blank()
        apply_event(s, SetTitle("htop", 0))
        self.assertEqual(s.title, "htop")

    def test_title_none_by_default(self):
        s = blank()
        self.assertIsNone(s.title)

    def test_title_overwrites(self):
        s = blank()
        apply_event(s, SetTitle("first", 0))
        apply_event(s, SetTitle("second", 5))
        self.assertEqual(s.title, "second")

    def test_title_captured_via_parser(self):
        s = blank()
        events = ANSIParser().parse(b"\x1b]0;My App\x07")
        for e in events:
            apply_event(s, e)
        self.assertEqual(s.title, "My App")

    def test_snapshot_copies_title(self):
        s = blank()
        apply_event(s, SetTitle("test", 0))
        snap = s.snapshot()
        self.assertEqual(snap.title, "test")


class TestSaveRestore(unittest.TestCase):
    def test_save_restore(self):
        s = blank()
        apply_event(s, MoveCursor(2, 3, True, 0))
        apply_event(s, SaveCursor(0))
        apply_event(s, MoveCursor(0, 0, True, 0))
        apply_event(s, RestoreCursor(0))
        self.assertEqual((s.cursor_row, s.cursor_col), (2, 3))


class TestAccessibilityObserver(unittest.TestCase):
    def _collect(self):
        events = []
        return events, events.append

    def test_title_emits_announcement(self):
        s = blank()
        seen, obs = self._collect()
        apply_event(s, SetTitle("htop", 0), obs)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0].kind, "title")
        self.assertIn("htop", seen[0].text)

    def test_full_clear_emits_announcement(self):
        s = blank(rows=3, cols=5)
        seen, obs = self._collect()
        apply_event(s, ClearScreen(2, 0), obs)
        self.assertEqual(seen[0].kind, "screen_cleared")

    def test_partial_clear_is_silent(self):
        s = blank(rows=3, cols=5)
        seen, obs = self._collect()
        apply_event(s, ClearScreen(0, 0), obs)  # cursor->end only
        self.assertEqual(seen, [])

    def test_printing_does_not_announce(self):
        s = blank()
        seen, obs = self._collect()
        apply_event(s, PrintChar("a", Style(), 0), obs)
        self.assertEqual(seen, [])

    def test_observer_optional_still_mutates(self):
        # No observer passed: behavior unchanged, title still recorded.
        s = blank()
        apply_event(s, SetTitle("x", 0))
        self.assertEqual(s.title, "x")


if __name__ == "__main__":
    unittest.main()

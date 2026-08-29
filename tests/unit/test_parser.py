"""unit tests for parser (T2/T2b) + OSC (window title) and wide chars."""

from __future__ import annotations
import unittest
from src.parser import ANSIParser
from src.contracts import (
    SetTitle, SetStyle, PrintChar, MoveCursor, ClearScreen, ClearLine,
    SaveCursor, RestoreCursor, UnknownSequence, Style
)


def evs(data):
    return ANSIParser().parse(data)


class TestPrinting(unittest.TestCase):
    def test_plain_text(self):
        out = evs(b"abc")
        self.assertEqual([e.char for e in out], ["a", "b", "c"])

    def test_byte_offsets(self):
        out = evs(b"abc")
        self.assertEqual([e.byte_offset for e in out], [0, 1, 2])

    def test_tab(self):
        out = evs(b"\t")
        self.assertEqual(out[0].char, "\t")

    def test_lf_cr(self):
        out = evs(b"a\nb\rc")
        chars = [e.char for e in out]
        self.assertIn("\n", chars)
        self.assertIn("\r", chars)

    def test_backspace(self):
        out = evs(b"a\x08b")
        self.assertEqual(out[1].col, -1)


class TestCursorMovement(unittest.TestCase):
    def test_cuu(self):
        self.assertEqual(evs(b"\x1b[3A"), [MoveCursor(-3, 0, False, 0)])

    def test_cud(self):
        self.assertEqual(evs(b"\x1b[2B"), [MoveCursor(2, 0, False, 0)])

    def test_cuf(self):
        self.assertEqual(evs(b"\x1b[5C"), [MoveCursor(0, 5, False, 0)])

    def test_cub(self):
        self.assertEqual(evs(b"\x1b[2D"), [MoveCursor(0, -2, False, 0)])

    def test_cup(self):
        self.assertEqual(evs(b"\x1b[2;3H"), [MoveCursor(1, 2, True, 0)])


class TestErase(unittest.TestCase):
    def test_ed(self):
        self.assertEqual(evs(b"\x1b[J"), [ClearScreen(0, 0)])

    def test_el(self):
        self.assertEqual(evs(b"\x1b[K"), [ClearLine(0, 0)])


class TestSGR(unittest.TestCase):
    def test_red(self):
        self.assertEqual(evs(b"\x1b[31m")[-1].style.fg_color, "red")

    def test_bold(self):
        self.assertEqual(evs(b"\x1b[1m")[-1].style.bold, True)

    def test_reset(self):
        self.assertEqual(evs(b"\x1b[0m")[-1].style, Style())


class TestOSC(unittest.TestCase):
    def test_osc0_bel(self):
        out = evs(b"\x1b]0;htop\x07")
        self.assertEqual(len(out), 1)
        self.assertIsInstance(out[0], SetTitle)
        self.assertEqual(out[0].title, "htop")

    def test_osc2_bel(self):
        out = evs(b"\x1b]2;My Terminal\x07")
        self.assertEqual(out[0].title, "My Terminal")

    def test_osc_st(self):
        out = evs(b"\x1b]0;title\x1b\\")
        self.assertEqual(out[0].title, "title")

    def test_osc_unknown_code(self):
        out = evs(b"\x1b]52;c;Ym9v\x07")
        self.assertIsInstance(out[0], UnknownSequence)


class TestEdgeCases(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(evs(b""), [])

    def test_lone_esc(self):
        out = evs(b"\x1b")
        self.assertTrue(any(isinstance(e, UnknownSequence) for e in out))

    def test_malformed_never_crashes(self):
        for raw in [b"\x1b[", b"\xff\xfe", b"\xc3", b"\xe2\x82"]:
            with self.subTest(raw=raw):
                ANSIParser().parse(raw)


if __name__ == "__main__":
    unittest.main()

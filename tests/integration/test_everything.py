"""Everything test: one end-to-end suite covering every feature.

Runs the full public surface — CLI, runner, parser, screen, diff, config,
accessibility, and logging — exactly as a user would use it. Deterministic
across OSes: ``echo`` commands (subprocess fallback on Windows), raw-bytes
parsing for wide chars / OSC titles, and hand-built screens for scrolls.

Run:  python -m unittest tests.integration.test_everything -v
"""

from __future__ import annotations

import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

from src.cli import main, create_parser
from src.config import load_config
from src.contracts import ScreenState
from src.diff import format_diff, diff_screens
from src.parser import ANSIParser
from src.screen import apply_events, render_as_text
from src.logger import configure_logging


# --------------------------------------------------------------------------- #
# 1. Zero dependency proof
# --------------------------------------------------------------------------- #

class TestZeroDependency(unittest.TestCase):
    def test_no_third_party_modules_imported(self) -> None:
        """Import every src module, then assert no packages slipped in."""
        for name in ("parser", "screen", "diff", "runner", "cli", "config",
                     "accessibility", "contracts", "logger"):
            importlib.import_module(f"src.{name}")

        forbidden = {
            "pyte", "pexpect", "colorama", "click", "typer", "tomli",
            "pydantic", "pyttsx3", "comtypes", "pyobjc", "pyatspi",
            "winpty", "pyyaml", "yaml", "requests", "numpy", "pytest",
        }
        present = sorted(set(forbidden) & set(sys.modules))
        self.assertEqual(present, [], f"third-party modules imported: {present}")


# --------------------------------------------------------------------------- #
# 2. Parser features (bytes in, events out)
# --------------------------------------------------------------------------- #

class TestParserFeatures(unittest.TestCase):
    def test_os0_window_title(self) -> None:
        events = ANSIParser().parse(b"\x1b]0;htop\x07")
        self.assertEqual(len(events), 1)
        self.assertEqual(getattr(events[0], "title", None), "htop")

    def test_os2_title_with_esc_st_terminator(self) -> None:
        events = ANSIParser().parse(b"\x1b]2;My App\x1b\\")
        self.assertEqual(getattr(events[0], "title", None), "My App")

    def test_sgr_color_style(self) -> None:
        events = ANSIParser().parse(b"\x1b[31mX")
        self.assertEqual(events[-1].char, "X")
        self.assertEqual(events[-1].style.fg_color, "red")

    def test_erase_line_emits_clearlane_event(self) -> None:
        events = ANSIParser().parse(b"\x1b[2K")
        self.assertEqual(type(events[0]).__name__, "ClearLine")

    def test_unknown_sequence_never_crashes(self) -> None:
        # Mouse-tracking / exotic CSI: must degrade to UnknownSequence.
        events = ANSIParser().parse(b"\x1b[?1000h")
        self.assertTrue(len(events) >= 1)


# --------------------------------------------------------------------------- #
# 3. Screen features
# --------------------------------------------------------------------------- #

class TestScreenPipeline(unittest.TestCase):
    def test_wide_emoji_takes_two_columns(self) -> None:
        state = ScreenState.blank(rows=2, cols=10)
        apply_events(state, ANSIParser().parse(b"A\xf0\x9f\x98\x8e"))
        self.assertEqual(state.cursor_col, 3)   # 'A'=1 + emoji=2
        self.assertEqual(state.grid[0][1].char, "😎")  # emoji landed one slot

    def test_title_extracted_into_state(self) -> None:
        state = ScreenState.blank(3, 10)
        apply_events(state, ANSIParser().parse(b"\x1b]0;htop\x07"))
        self.assertEqual(state.title, "htop")

    def test_respects_terminal_geometry(self) -> None:
        state = ScreenState.blank(rows=4, cols=6)
        apply_events(state, ANSIParser().parse(b"abcdefgh"))
        self.assertEqual(len(state.grid), 4)          # rows fixed
        self.assertEqual(render_as_text(state)[0], "abcdef")


# --------------------------------------------------------------------------- #
# 4. Diff features
# --------------------------------------------------------------------------- #

class TestDiffFeatures(unittest.TestCase):
    def test_cell_by_cell_changes(self) -> None:
        before = ScreenState.blank(3, 5)
        after = ScreenState.blank(3, 5)
        apply_events(after, ANSIParser().parse(b"hi"))
        diff = diff_screens(before, after)
        self.assertGreater(len(diff.changes), 0)
        self.assertTrue(diff.cursor_moved)

    def test_scroll_detection(self) -> None:
        before = ScreenState.blank(4, 6)
        after = ScreenState.blank(4, 6)
        for row in range(4):
            for col in range(6):
                before.grid[row][col].char = chr(65 + row)  # A,A,A...(row 0), B,B...
        # Everything shifts up: after[row] == before[row+1]; new blank bottom.
        for row in range(3):
            for col in range(6):
                after.grid[row][col].char = before.grid[row + 1][col].char
        diff = diff_screens(before, after)
        self.assertTrue(diff.scrolled, "expected scroll detection")

    def test_format_diff_colors_old_red_new_green(self) -> None:
        before = ScreenState.blank(1, 4)
        after = ScreenState.blank(1, 4)
        apply_events(after, ANSIParser().parse(b"ab"))
        out = format_diff(diff_screens(before, after), color=True)
        self.assertIn("\x1b[31m", out)   # red for old
        self.assertIn("\x1b[32m", out)   # green for new

    def test_format_diff_plain_has_no_ansi(self) -> None:
        before = ScreenState.blank(1, 4)
        after = ScreenState.blank(1, 4)
        apply_events(after, ANSIParser().parse(b"ab"))
        out = format_diff(diff_screens(before, after), color=False)
        self.assertNotIn("\x1b[", out)


# --------------------------------------------------------------------------- #
# 5. Config feature
# --------------------------------------------------------------------------- #

class TestConfigFeature(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".toml", delete=False, encoding="utf-8"
        )
        self._tmp.write("[terminal]\nrows = 40\ncols = 111\n[color]\nenabled = false\n")
        self._tmp.close()

    def tearDown(self) -> None:
        os.unlink(self._tmp.name)

    def test_config_toml_loaded(self) -> None:
        cfg = load_config(self._tmp.name, env={})
        self.assertEqual(cfg.terminal.rows, 40)
        self.assertEqual(cfg.terminal.cols, 111)
        self.assertFalse(cfg.color.enabled)

    def test_env_overrides_file(self) -> None:
        cfg = load_config(
            self._tmp.name,
            env={"TERMIREQ_ROWS": "50", "TERMIREQ_COLOR": "yes"},
        )
        self.assertEqual(cfg.terminal.rows, 50)   # env wins
        self.assertTrue(cfg.color.enabled)


# --------------------------------------------------------------------------- #
# 6. Accessibility feature
# --------------------------------------------------------------------------- #

class TestAccessibilityFeature(unittest.TestCase):
    def test_stream_backend_emits_announcement(self) -> None:
        err = io.StringIO()
        out = io.StringIO()
        with redirect_stderr(err):
            with redirect_stdout(out):
                rc = main(["run", "echo hi", "--a11y-backend", "stream", "--no-color"])
        self.assertEqual(rc, 0)
        self.assertIn("command_finished", err.getvalue())

    def test_announcement_summary_content(self) -> None:
        # summarize_diff produces the spoken sentence (unit-level anchor).
        from src.accessibility import summarize_diff
        from src.contracts import DiffResult
        diff = DiffResult(changes=[], cursor_moved=False, new_cursor=(0, 0))
        anns = summarize_diff("ls", 0, diff)
        self.assertEqual(anns[0].kind, "command_finished")
        self.assertIn("No visible changes", anns[0].text)


# --------------------------------------------------------------------------- #
# 7. Logging feature
# --------------------------------------------------------------------------- #

class TestLoggingFeature(unittest.TestCase):
    def test_verbose_produces_info_logs_but_clean_stdout(self) -> None:
        err = io.StringIO()
        out = io.StringIO()
        with redirect_stderr(err):
            with redirect_stdout(out):
                rc = main(["run", "echo hi", "--no-color", "--verbose"])
        self.assertEqual(rc, 0)
        self.assertIn("[INFO]", err.getvalue())
        self.assertNotIn("[INFO]", out.getvalue())   # logs never on stdout

    def test_debug_produces_debug_logs(self) -> None:
        err = io.StringIO()
        out = io.StringIO()
        with redirect_stderr(err):
            with redirect_stdout(out):
                rc = main(["run", "echo hi", "--no-color", "--debug"])
        self.assertEqual(rc, 0)
        self.assertIn("[DEBUG]", err.getvalue())

    def test_configure_logging_idempotent(self) -> None:
        r1 = configure_logging(verbose=True)
        r2 = configure_logging(verbose=False)
        self.assertEqual(len(r1.handlers), len(r2.handlers))


# --------------------------------------------------------------------------- #
# 8. CLI: full pipeline end-to-end
# --------------------------------------------------------------------------- #

class TestCLIEndToEnd(unittest.TestCase):
    def _run(self, *args) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = main(list(args))
        return rc, out.getvalue(), err.getvalue()

    def test_single_command(self) -> None:
        rc, out, _ = self._run("run", "echo hello", "--no-color")
        self.assertEqual(rc, 0)
        self.assertIn("finished", out)
        self.assertIn("Row", out)                  # diff block present

    def test_multiple_commands_sequential(self) -> None:
        rc, out, _ = self._run("run", "echo one", "echo two", "--no-color")
        self.assertEqual(rc, 0)
        self.assertEqual(out.count("finished"), 2)  # one diff per command

    def test_json_flag_outputs_serializable_diff(self) -> None:
        rc, out, _ = self._run("run", "echo hello", "--json")
        self.assertEqual(rc, 0)
        data = json.loads(out)                     # must be valid JSON
        self.assertIn("exit_code", data)
        self.assertIn("diff", data)

    def test_no_color_flag_forces_plain_text(self) -> None:
        rc, out, _ = self._run("run", "echo hi", "--no-color")
        self.assertEqual(rc, 0)
        self.assertNotIn("\x1b[", out)

    def test_cli_flags_parse(self) -> None:
        parser = create_parser()
        cases = {
            "--json": "json",
            "--no-color": "no_color",
            "--accessibility": "accessibility",
            "--speak": "speak",
            "--verbose": "verbose",
            "--debug": "debug",
        }
        for flag, attr in cases.items():
            args = parser.parse_args(["run", "x", flag])
            self.assertTrue(getattr(args, attr), flag)
        args = parser.parse_args(["run", "x", "-v"])   # short form
        self.assertTrue(args.verbose)


if __name__ == "__main__":
    unittest.main(verbosity=2)
"""cli unit tests."""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

from src.cli import build_config, create_parser, main, resolve_color
from src.config import Config


class TestCLI(unittest.TestCase):
    def setUp(self):
        self.parser = create_parser()

    def test_run_subcommand_parsing(self):
        args = self.parser.parse_args(["run", "ls", "echo hello"])
        self.assertEqual(args.subcommand, "run")
        self.assertEqual(args.commands, ["ls", "echo hello"])

    def test_missing_subcommand(self):
        with self.assertRaises(SystemExit):
            with open(os.devnull, "w") as f:
                original_stderr = sys.stderr
                try:
                    sys.stderr = f
                    self.parser.parse_args([])
                finally:
                    sys.stderr = original_stderr

    def test_new_flags_parse(self):
        args = self.parser.parse_args(
            ["run", "ls", "--no-color", "--accessibility",
             "--a11y-backend", "stream", "--config", "c.toml"]
        )
        self.assertTrue(args.no_color)
        self.assertTrue(args.accessibility)
        self.assertEqual(args.a11y_backend, "stream")
        self.assertEqual(args.config, "c.toml")


class TestResolveColor(unittest.TestCase):
    def test_no_color_flag_wins(self):
        cfg = Config()
        cfg.color.enabled = True
        self.assertFalse(resolve_color(cfg, no_color_flag=True))

    def test_config_value_used_when_set(self):
        cfg = Config()
        cfg.color.enabled = True
        self.assertTrue(resolve_color(cfg, no_color_flag=False))
        cfg.color.enabled = False
        self.assertFalse(resolve_color(cfg, no_color_flag=False))


class TestBuildConfig(unittest.TestCase):
    def _args(self, **kw):
        args = create_parser().parse_args(["run", "x"])
        for k, v in kw.items():
            setattr(args, k, v)
        return args

    def test_speak_forces_speech_backend(self):
        cfg = build_config(self._args(speak=True))
        self.assertTrue(cfg.accessibility.enabled)
        self.assertEqual(cfg.accessibility.backend, "speech")

    def test_accessibility_flag_enables(self):
        cfg = build_config(self._args(accessibility=True))
        self.assertTrue(cfg.accessibility.enabled)

    def test_a11y_backend_override(self):
        cfg = build_config(self._args(a11y_backend="stream"))
        self.assertTrue(cfg.accessibility.enabled)
        self.assertEqual(cfg.accessibility.backend, "stream")


class TestMainEndToEnd(unittest.TestCase):
    def test_run_echo_returns_zero(self):
        # Uses the subprocess fallback on Windows / PTY elsewhere.
        cmd = "echo hello"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["run", cmd, "--no-color"])
        self.assertEqual(rc, 0)
        self.assertIn("finished", buf.getvalue())

    def test_run_json_output(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["run", "echo hello", "--json"])
        self.assertEqual(rc, 0)
        self.assertIn('"exit_code"', buf.getvalue())


if __name__ == "__main__":
    unittest.main()

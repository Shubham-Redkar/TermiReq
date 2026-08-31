"""Unit tests for the logging & debugging tooling (Task 9)."""

from __future__ import annotations

import io
import logging
import os
import unittest
from contextlib import redirect_stdout

from src.cli import create_parser, main
from src.logger import configure_logging, get_logger, _resolve_level


class TestGetLogger(unittest.TestCase):
    def test_namespaced_under_termireq(self) -> None:
        self.assertEqual(get_logger("parser").name, "termireq.parser")

    def test_src_modules_stay_namespaced(self) -> None:
        self.assertEqual(get_logger("src.diff").name, "termireq.src.diff")


class TestResolveLevel(unittest.TestCase):
    def test_debug_wins_over_verbose(self) -> None:
        self.assertEqual(
            _resolve_level(verbose=True, debug=True, env_level=None),
            logging.DEBUG,
        )

    def test_verbose_is_info(self) -> None:
        self.assertEqual(
            _resolve_level(verbose=True, debug=False, env_level=None),
            logging.INFO,
        )

    def test_env_level_used_when_no_flags(self) -> None:
        self.assertEqual(
            _resolve_level(verbose=False, debug=False, env_level="DEBUG"),
            logging.DEBUG,
        )

    def test_default_is_warning(self) -> None:
        self.assertEqual(
            _resolve_level(verbose=False, debug=False, env_level=None),
            logging.WARNING,
        )

    def test_bad_env_level_falls_back_to_warning(self) -> None:
        self.assertEqual(
            _resolve_level(verbose=False, debug=False, env_level="loud"),
            logging.WARNING,
        )


class TestConfigureLogging(unittest.TestCase):
    def test_configure_is_idempotent(self) -> None:
        root = configure_logging(verbose=True)
        before = len(root.handlers)
        root = configure_logging(verbose=False)
        self.assertEqual(len(root.handlers), before)  # never stacks handlers
        self.assertEqual(root.level, logging.WARNING)

    def test_level_set_from_verbose(self) -> None:
        root = configure_logging(verbose=True)
        self.assertEqual(root.level, logging.INFO)


class TestCLILoggingFlags(unittest.TestCase):
    def test_verbose_flag_parses(self) -> None:
        args = create_parser().parse_args(["run", "ls", "-v"])
        self.assertTrue(args.verbose)

    def test_debug_flag_parses(self) -> None:
        args = create_parser().parse_args(["run", "ls", "--debug"])
        self.assertTrue(args.debug)

    def test_run_with_verbose_keeps_stdout_clean(self) -> None:
        # Logging goes to stderr; the diff/status stays on stdout.
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = main(["run", "echo hello", "--no-color", "--verbose"])
        self.assertEqual(rc, 0)
        self.assertIn("finished", buf.getvalue())

    def test_env_log_level_respected_by_main(self) -> None:
        old = os.environ.get("TERMIREQ_LOG_LEVEL")
        os.environ["TERMIREQ_LOG_LEVEL"] = "debug"
        try:
            root = configure_logging()
            self.assertEqual(root.level, logging.DEBUG)
        finally:
            if old is None:
                os.environ.pop("TERMIREQ_LOG_LEVEL", None)
            else:
                os.environ["TERMIREQ_LOG_LEVEL"] = old


if __name__ == "__main__":
    unittest.main()
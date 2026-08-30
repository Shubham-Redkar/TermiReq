"""cli unit tests."""

import os
import sys
import unittest

from src.cli import create_parser


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


if __name__ == "__main__":
    unittest.main()

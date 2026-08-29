"""cli unit tests."""

import unittest
import sys
from src.cli import create_parser, main

class TestCLI(unittest.TestCase):
    def setUp(self):
        self.parser = create_parser()

    def test_run_subcommand_parsing(self):
        args = self.parser.parse_args(["run", "ls", "echo hello"])
        self.assertEqual(args.subcommand, "run")
        self.assertEqual(args.commands, ["ls", "echo hello"])

    def test_missing_subcommand(self):
        with self.assertRaises(SystemExit):
            with open('/dev/null', 'w') as f:
                sys.stderr = f
                self.parser.parse_args([])
            sys.stderr = sys.__stderr__

if __name__ == "__main__":
    unittest.main()

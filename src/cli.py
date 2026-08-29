"""command line interface (T5/T6a/T7)."""

import argparse
import sys
from typing import List

def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="TermiReq (tyydiff): Terminal screen diffing tool."
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    run_parser = subparsers.add_parser(
        "run",
        help="Run commands sequentially and diff their terminal outputs."
    )
    run_parser.add_argument(
        "commands",
        nargs="+",
        help="One or more shell commands to execute"
    )

    return parser

def main(args: List[str] | None = None) -> int:
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.subcommand == "run":
        # Placeholder for T6a/T7 Runner Integration
        print(f"CLI Skeleton initialized. Commands to run: {parsed_args.commands}")
        return 0

    return 1

if __name__ == "__main__":
    sys.exit(main())

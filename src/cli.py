"""Command line interface (T5/T6a/T7).

This module provides the main entrypoint for the TermiReq CLI. It parses
user arguments, orchestrates the PTY runner and parser, and formats the
output (either as human-readable text or machine-readable JSON).

The CLI supports three core flows:
1. `run`: Execute live shell commands, rendering and diffing their output sequentially.
2. `record`: Run a command and dump its raw PTY byte stream straight to a binary file.
3. `replay`: Read a recorded session, parse the bytes, and output the visual diff.
"""

import argparse
import dataclasses
import json
import os
import sys
from typing import List

from src.contracts import ScreenState, Cell, CommandChunk, CommandFinished
from src.runner import (
    run_commands,
    detect_terminal_geometry,
    describe_platform,
)
from src.parser import ANSIParser
from src.screen import apply_events
from src.diff import diff_screens, format_diff, DiffResult
from src.config import Config, load_config
from src.accessibility import AccessibilityAdapter, get_adapter, summarize_diff
from src.logger import configure_logging, get_logger

logger = get_logger(__name__)

def create_parser() -> argparse.ArgumentParser:
    """Create and configure the CLI argument parser."""
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
    run_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Maximum time in seconds to wait for a command to finish"
    )
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Output diff as machine-readable JSON"
    )
    run_parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to a config.toml (overrides the search path)"
    )
    run_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color in the diff output"
    )
    run_parser.add_argument(
        "--accessibility",
        action="store_true",
        help="Emit accessibility announcements of what changed"
    )
    run_parser.add_argument(
        "--a11y-backend",
        choices=["auto", "speech", "stream", "null"],
        default=None,
        help="Accessibility backend to use (implies --accessibility)"
    )
    run_parser.add_argument(
        "--speak",
        action="store_true",
        help="Read the diff out loud (alias for --accessibility --a11y-backend speech)"
    )
    run_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log pipeline steps to stderr at INFO level"
    )
    run_parser.add_argument(
        "--debug",
        action="store_true",
        help="Log per-event detail to stderr at DEBUG level (implies verbose)"
    )

    record_parser = subparsers.add_parser(
        "record",
        help="Run a command and record its raw byte stream to a file."
    )
    record_parser.add_argument(
        "command",
        help="A single shell command to execute and record"
    )
    record_parser.add_argument(
        "--output",
        "-o",
        required=True,
        help="Path to the binary file where the session will be recorded"
    )
    record_parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="Maximum time in seconds to wait for a command to finish"
    )
    record_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log pipeline steps to stderr at INFO level"
    )
    record_parser.add_argument(
        "--debug",
        action="store_true",
        help="Log per-event detail to stderr at DEBUG level (implies verbose)"
    )

    replay_parser = subparsers.add_parser(
        "replay",
        help="Replay a recorded terminal byte stream from a file and calculate the diff."
    )
    replay_parser.add_argument(
        "input",
        help="Path to the recorded binary session file"
    )
    replay_parser.add_argument(
        "--json",
        action="store_true",
        help="Output diff as machine-readable JSON"
    )
    replay_parser.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to a config.toml (overrides the search path)"
    )
    replay_parser.add_argument(
        "--no-color",
        action="store_true",
        help="Disable ANSI color in the diff output"
    )
    replay_parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Log pipeline steps to stderr at INFO level"
    )
    replay_parser.add_argument(
        "--debug",
        action="store_true",
        help="Log per-event detail to stderr at DEBUG level (implies verbose)"
    )

    return parser

def create_empty_state(rows: int, cols: int) -> ScreenState:
    """Create a blank ScreenState for a given terminal geometry."""
    return ScreenState(
        rows=rows,
        cols=cols,
        grid=[[Cell(char=" ") for _ in range(cols)] for _ in range(rows)],
        cursor_row=0,
        cursor_col=0,
    )


def _should_colorize() -> bool:
    """Decide whether diff output should include ANSI color.

    Honors the NO_COLOR convention (https://no-color.org) and only colorizes
    when stdout is an interactive terminal, so escape codes never end up in a
    redirected file or a downstream pipe.
    """
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def resolve_color(config: Config, *, no_color_flag: bool) -> bool:
    """Combine the --no-color flag, config, and auto-detection into a decision.

    Precedence: an explicit ``--no-color`` wins; then a config value if set;
    otherwise fall back to :func:`_should_colorize` (tty + NO_COLOR aware).
    """
    if no_color_flag:
        return False
    if config.color.enabled is not None:
        return config.color.enabled
    return _should_colorize()


def build_config(parsed_args) -> Config:
    """Load config from disk/env, then layer CLI-flag overrides on top."""
    config = load_config(getattr(parsed_args, "config", None))

    # CLI accessibility flags override the file/env config.
    if getattr(parsed_args, "speak", False):
        config.accessibility.enabled = True
        config.accessibility.backend = "speech"
    if getattr(parsed_args, "accessibility", False):
        config.accessibility.enabled = True
    if getattr(parsed_args, "a11y_backend", None):
        config.accessibility.enabled = True
        config.accessibility.backend = parsed_args.a11y_backend

    return config


def print_diff(diff_result: DiffResult, *, color: bool = True) -> None:
    """Format and print the diff result to stdout for a human reader."""
    print(format_diff(diff_result, color=color))

def main(args: List[str] | None = None) -> int:
    """Main CLI execution flow.
    
    This function acts as the central controller for the application. It routes
    execution based on the chosen subcommand (`run`, `record`, or `replay`).
    It orchestrates the terminal size detection, instantiates the accessibility
    adapters, reads from the runner or binary files, and funnels bytes into the
    ANSIParser and ScreenState to calculate final visual diffs.
    """
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.subcommand == "run":
        root_logger = configure_logging(
            verbose=parsed_args.verbose,
            debug=parsed_args.debug,
        )
        root_logger.debug(
            "CLI args=%s verbose=%s debug=%s", parsed_args, parsed_args.verbose, parsed_args.debug
        )

        config = build_config(parsed_args)

        # Detect the real terminal size once and use it for BOTH the PTY
        # (via run_commands) and our virtual screen. They must match, or the
        # program's output is formatted for a different width than the grid we
        # diff against and changes get silently truncated. Config values, when
        # set, take precedence over auto-detection.
        detected_rows, detected_cols = detect_terminal_geometry()
        rows = config.terminal.rows or detected_rows
        cols = config.terminal.cols or detected_cols
        root_logger.debug(
            "geometry detected=%s config=%s using=%s",
            (detected_rows, detected_cols),
            (config.terminal.rows, config.terminal.cols),
            (rows, cols),
        )

        use_color = resolve_color(config, no_color_flag=parsed_args.no_color)
        root_logger.debug(
            "color_enabled=%s (no_color_flag=%s, config=%s, stdout_tty=%s)",
            use_color, parsed_args.no_color, config.color.enabled, sys.stdout.isatty(),
        )

        # Build the accessibility adapter once for the whole run. When disabled
        # this is a NullAdapter and the observer stays off the hot path.
        adapter = get_adapter(config.accessibility)
        observer = adapter.announce if adapter.available else None
        verbosity = config.accessibility.verbosity
        root_logger.info(
            "platform=%s a11y_backend=%s observer=%s",
            describe_platform(),
            config.accessibility.backend,
            "active" if observer is not None else "inactive",
        )

        runner_events = run_commands(parsed_args.commands, timeout=parsed_args.timeout, rows=rows, cols=cols)

        current_state = create_empty_state(rows, cols)
        before_state = current_state.snapshot()
        ansi_parser = ANSIParser()
        root_logger.debug(
            "pipeline ready screen=%dx%d parser=%s", rows, cols, type(ansi_parser).__name__
        )

        try:
            for event in runner_events:
                if isinstance(event, CommandChunk):
                    root_logger.debug(
                        "CommandChunk cmd=%r bytes=%d",
                        event.command, len(event.data),
                    )
                    # Stream parser events straight into the screen instead of
                    # materializing an intermediate list (batch processing).
                    apply_events(
                        current_state,
                        ansi_parser.feed(event.data),
                        observer=observer,
                    )

                elif isinstance(event, CommandFinished):
                    after_state = current_state.snapshot()
                    diff_result = diff_screens(before_state, after_state)
                    root_logger.info(
                        "command_finished cmd=%r exit_code=%s changes=%d scrolled=%s",
                        event.command, event.exit_code, len(diff_result.changes),
                        diff_result.scrolled,
                    )

                    if parsed_args.json:
                        data = {
                            "command": event.command,
                            "exit_code": event.exit_code,
                            "diff": dataclasses.asdict(diff_result)
                        }
                        print(json.dumps(data, indent=2))
                    else:
                        print(f"--- Command '{event.command}' finished (exit code {event.exit_code}) ---")
                        print_diff(diff_result, color=use_color)

                    if adapter.available:
                        adapter.announce_all(
                            summarize_diff(
                                event.command,
                                event.exit_code,
                                diff_result,
                                verbosity=verbosity,
                            )
                        )

                    # Reset for next command
                    current_state = create_empty_state(rows, cols)
                    before_state = current_state.snapshot()
                    ansi_parser = ANSIParser()
        finally:
            adapter.close()

        return 0

    elif parsed_args.subcommand == "record":
        root_logger = configure_logging(verbose=parsed_args.verbose, debug=parsed_args.debug)
        detected_rows, detected_cols = detect_terminal_geometry()
        runner_events = run_commands([parsed_args.command], timeout=parsed_args.timeout, rows=detected_rows, cols=detected_cols)
        
        with open(parsed_args.output, "wb") as f:
            for event in runner_events:
                if isinstance(event, CommandChunk):
                    f.write(event.data)
                elif isinstance(event, CommandFinished):
                    print(f"--- Command '{event.command}' recorded (exit code {event.exit_code}) ---")
        return 0

    elif parsed_args.subcommand == "replay":
        root_logger = configure_logging(verbose=parsed_args.verbose, debug=parsed_args.debug)
        config = build_config(parsed_args)
        
        detected_rows, detected_cols = detect_terminal_geometry()
        rows = config.terminal.rows or detected_rows
        cols = config.terminal.cols or detected_cols
        use_color = resolve_color(config, no_color_flag=parsed_args.no_color)
        
        adapter = get_adapter(config.accessibility)
        observer = adapter.announce if adapter.available else None
        verbosity = config.accessibility.verbosity
        
        try:
            with open(parsed_args.input, "rb") as f:
                data = f.read()
                
            current_state = create_empty_state(rows, cols)
            before_state = current_state.snapshot()
            ansi_parser = ANSIParser()
            
            apply_events(current_state, ansi_parser.feed(data), observer=observer)
            
            diff_result = diff_screens(before_state, current_state)
            if parsed_args.json:
                out_data = {
                    "command": f"replay {parsed_args.input}",
                    "exit_code": 0,
                    "diff": dataclasses.asdict(diff_result)
                }
                print(json.dumps(out_data, indent=2))
            else:
                print(f"--- Replay '{parsed_args.input}' finished ---")
                print_diff(diff_result, color=use_color)
                
            if adapter.available:
                adapter.announce_all(
                    summarize_diff(
                        f"replay {parsed_args.input}",
                        0,
                        diff_result,
                        verbosity=verbosity,
                    )
                )
        finally:
            adapter.close()
            
        return 0

    return 1

if __name__ == "__main__":
    sys.exit(main())

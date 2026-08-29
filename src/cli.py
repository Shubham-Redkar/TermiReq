"""command line interface (T5/T6a/T7)."""

import argparse
import sys
from typing import List

from src.contracts import ScreenState, Cell, CommandChunk, CommandFinished
from src.runner import run_commands
from src.parser import ANSIParser
from src.screen import apply_events
from src.diff import diff_screens

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
    run_parser.add_argument(
        "--json",
        action="store_true",
        help="Output diff as machine-readable JSON"
    )
    run_parser.add_argument(
        "--speak",
        action="store_true",
        help="Read the diff out loud (macOS/Linux)"
    )

    return parser

def create_empty_state(rows: int, cols: int) -> ScreenState:
    return ScreenState(
        rows=rows,
        cols=cols,
        grid=[[Cell(char=" ") for _ in range(cols)] for _ in range(rows)],
        cursor_row=0,
        cursor_col=0,
    )

import json
import dataclasses
import platform
import subprocess

def speak_summary(command: str, diff_result) -> None:
    num_changes = len(diff_result.changes)
    summary = f"Command {command} finished. "
    if getattr(diff_result, "scrolled", False):
        summary += f"Screen scrolled {diff_result.scroll_direction} by {diff_result.scroll_amount} lines. "
    summary += f"{num_changes} cells changed on screen."

    sys_name = platform.system()
    try:
        if sys_name == "Darwin":
            subprocess.run(["say", summary], check=False)
        elif sys_name == "Linux":
            # Slow down speed (-s 130), set pitch (-p 50), add word gap (-g 2), use female voice 3 (-v en+f3)
            subprocess.run(["espeak", "-s", "130", "-p", "50", "-g", "2", "-v", "en+f3", summary], check=False, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        pass  # Speech engine not installed

def print_diff(diff_result) -> None:
    if getattr(diff_result, "scrolled", False):
        print(f"  [Scrolled {diff_result.scroll_direction} by {diff_result.scroll_amount} lines]")
    
    if diff_result.cursor_moved:
        print(f"  [Cursor moved to {diff_result.new_cursor}]")
        
    for change in diff_result.changes:
        old_char = change.old.char if change.old.char != " " else "<space>"
        new_char = change.new.char if change.new.char != " " else "<space>"
        print(f"  Row {change.row:02} Col {change.col:02}: {old_char!r} -> {new_char!r}")
        
    if not diff_result.changes and not getattr(diff_result, "scrolled", False) and not diff_result.cursor_moved:
        print("  [No changes detected]")

def main(args: List[str] | None = None) -> int:
    parser = create_parser()
    parsed_args = parser.parse_args(args)

    if parsed_args.subcommand == "run":
        rows = 24
        cols = 80
        
        runner_events = run_commands(parsed_args.commands, rows=rows, cols=cols)
        
        current_state = create_empty_state(rows, cols)
        before_state = current_state.snapshot()
        ansi_parser = ANSIParser()
        
        for event in runner_events:
            if isinstance(event, CommandChunk):
                screen_events = ansi_parser.parse(event.data)
                apply_events(current_state, screen_events)
                
            elif isinstance(event, CommandFinished):
                after_state = current_state.snapshot()
                diff_result = diff_screens(before_state, after_state)
                
                if parsed_args.json:
                    data = {
                        "command": event.command,
                        "exit_code": event.exit_code,
                        "diff": dataclasses.asdict(diff_result)
                    }
                    print(json.dumps(data, indent=2))
                else:
                    print(f"--- Command '{event.command}' finished (exit code {event.exit_code}) ---")
                    print_diff(diff_result)
                
                if parsed_args.speak:
                    speak_summary(event.command, diff_result)
                
                # Reset for next command
                current_state = create_empty_state(rows, cols)
                before_state = current_state.snapshot()
                ansi_parser = ANSIParser()
                
        return 0

    return 1

if __name__ == "__main__":
    sys.exit(main())

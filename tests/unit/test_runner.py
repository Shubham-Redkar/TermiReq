"""Unit tests for the PTY command runner (T1/T1b)."""

from __future__ import annotations

import sys
import unittest
from collections.abc import Generator

from src.contracts import CommandChunk, CommandFinished, RunnerEvent
from src.runner import pty_supported, run_commands


def _collect_events(
    commands: list[str],
    **kwargs: object,
) -> list[RunnerEvent]:
    return list(run_commands(commands, **kwargs))


def _mock_runner(
    outputs: dict[str, bytes],
    exit_codes: dict[str, int] | None = None,
) -> object:
    codes = exit_codes or {}

    def _runner(
        command: str,
        command_index: int,
        *,
        timeout: float | None = None,
        rows: int = 24,
        cols: int = 80,
    ) -> Generator[RunnerEvent, None, None]:
        yield CommandChunk(
            command=command,
            data=outputs.get(command, b""),
            command_index=command_index,
        )
        yield CommandFinished(
            command=command,
            command_index=command_index,
            exit_code=codes.get(command, 0),
        )

    return _runner


class TestRunCommandsMocked(unittest.TestCase):
    def test_empty_command_list_yields_nothing(self) -> None:
        self.assertEqual(_collect_events([]), [])

    def test_single_command_yields_chunk_and_finished(self) -> None:
        events = _collect_events(
            ["echo hi"],
            use_pty=False,
            runner_fn=_mock_runner({"echo hi": b"hi\n"}),
        )
        self.assertEqual(len(events), 2)
        self.assertIsInstance(events[0], CommandChunk)
        self.assertIsInstance(events[1], CommandFinished)
        chunk = events[0]
        assert isinstance(chunk, CommandChunk)
        self.assertEqual(chunk.data, b"hi\n")
        self.assertEqual(chunk.command_index, 0)

    def test_multiple_commands_run_sequentially(self) -> None:
        events = _collect_events(
            ["first", "second"],
            use_pty=False,
            runner_fn=_mock_runner({"first": b"1", "second": b"2"}),
        )
        self.assertEqual(len(events), 4)
        chunks = [e for e in events if isinstance(e, CommandChunk)]
        self.assertEqual([c.command for c in chunks], ["first", "second"])
        self.assertEqual([c.command_index for c in chunks], [0, 1])
        finished = [e for e in events if isinstance(e, CommandFinished)]
        self.assertEqual(len(finished), 2)

    def test_subprocess_fallback_runs_echo(self) -> None:
        if sys.platform == "win32":
            command = 'echo hello'
        else:
            command = "echo hello"
        events = _collect_events([command], use_pty=False)
        chunk = events[0]
        assert isinstance(chunk, CommandChunk)
        self.assertIn(b"hello", chunk.data.lower())
        finished = events[1]
        assert isinstance(finished, CommandFinished)
        self.assertEqual(finished.exit_code, 0)

    def test_timeout_marks_command_as_timed_out(self) -> None:
        if sys.platform == "win32":
            command = "ping -n 6 127.0.0.1"
        else:
            command = "sleep 10"
        events = _collect_events([command], use_pty=False, timeout=0.2)
        finished = events[1]
        assert isinstance(finished, CommandFinished)
        self.assertTrue(finished.timed_out)


@unittest.skipUnless(pty_supported(), "PTY not available on this platform")
class TestRunCommandsPty(unittest.TestCase):
    def test_pty_echo_includes_output(self) -> None:
        events = _collect_events(["echo pty-test"], use_pty=True)
        chunk = events[0]
        assert isinstance(chunk, CommandChunk)
        self.assertIn(b"pty-test", chunk.data)
        finished = events[1]
        assert isinstance(finished, CommandFinished)
        self.assertEqual(finished.exit_code, 0)
        self.assertFalse(finished.timed_out)


class TestPtySupported(unittest.TestCase):
    def test_windows_reports_no_pty(self) -> None:
        if sys.platform == "win32":
            self.assertFalse(pty_supported())


if __name__ == "__main__":
    unittest.main()

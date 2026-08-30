"""Unit tests for the PTY command runner (T1/T1b)."""

from __future__ import annotations

import os
import sys
import unittest
from collections.abc import Generator
from unittest import mock

from src.contracts import CommandChunk, CommandFinished, RunnerEvent
from src.runner import (
    describe_platform,
    detect_terminal_geometry,
    is_wsl,
    pty_supported,
    run_commands,
)


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


class TestWslDetection(unittest.TestCase):
    def test_non_linux_is_not_wsl(self) -> None:
        with mock.patch("src.runner.sys") as fake_sys:
            fake_sys.platform = "win32"
            self.assertFalse(is_wsl())

    def test_env_var_flags_wsl(self) -> None:
        with mock.patch("src.runner.sys") as fake_sys, mock.patch.dict(
            os.environ, {"WSL_DISTRO_NAME": "Ubuntu"}, clear=False
        ):
            fake_sys.platform = "linux"
            self.assertTrue(is_wsl())

    def test_proc_version_microsoft_marker(self) -> None:
        m = mock.mock_open(read_data="Linux version 5.15.0-microsoft-standard")
        with mock.patch("src.runner.sys") as fake_sys, mock.patch.dict(
            os.environ, {}, clear=True
        ), mock.patch("builtins.open", m):
            fake_sys.platform = "linux"
            self.assertTrue(is_wsl())

    def test_describe_platform_mentions_backend(self) -> None:
        desc = describe_platform()
        self.assertTrue(
            any(word in desc for word in ("pty", "subprocess")),
            desc,
        )


class TestTerminalGeometry(unittest.TestCase):
    def test_detect_maps_columns_to_cols_and_lines_to_rows(self) -> None:
        fake = os.terminal_size((120, 40))  # (columns, lines)
        with mock.patch("src.runner.shutil.get_terminal_size", return_value=fake):
            rows, cols = detect_terminal_geometry()
        self.assertEqual((rows, cols), (40, 120))

    def test_detect_uses_fallback_when_size_is_zero(self) -> None:
        # Some environments report 0x0; we must not hand a 0-sized PTY down.
        fake = os.terminal_size((0, 0))
        with mock.patch("src.runner.shutil.get_terminal_size", return_value=fake):
            rows, cols = detect_terminal_geometry(fallback_rows=24, fallback_cols=80)
        self.assertEqual((rows, cols), (24, 80))

    def test_run_commands_autodetects_geometry_when_not_given(self) -> None:
        captured: dict[str, int] = {}

        def _recorder(
            command: str,
            command_index: int,
            *,
            timeout: float | None = None,
            rows: int = 24,
            cols: int = 80,
        ) -> Generator[RunnerEvent, None, None]:
            captured["rows"] = rows
            captured["cols"] = cols
            yield CommandChunk(command=command, data=b"", command_index=command_index)
            yield CommandFinished(
                command=command, command_index=command_index, exit_code=0
            )

        with mock.patch(
            "src.runner.detect_terminal_geometry", return_value=(50, 100)
        ):
            list(run_commands(["x"], use_pty=False, runner_fn=_recorder))

        self.assertEqual(captured, {"rows": 50, "cols": 100})

    def test_run_commands_respects_explicit_geometry(self) -> None:
        captured: dict[str, int] = {}

        def _recorder(
            command: str,
            command_index: int,
            *,
            timeout: float | None = None,
            rows: int = 24,
            cols: int = 80,
        ) -> Generator[RunnerEvent, None, None]:
            captured["rows"] = rows
            captured["cols"] = cols
            yield CommandChunk(command=command, data=b"", command_index=command_index)
            yield CommandFinished(
                command=command, command_index=command_index, exit_code=0
            )

        # Explicit values must bypass auto-detection entirely.
        with mock.patch(
            "src.runner.detect_terminal_geometry",
            side_effect=AssertionError("should not auto-detect"),
        ):
            list(
                run_commands(
                    ["x"], use_pty=False, runner_fn=_recorder, rows=10, cols=20
                )
            )

        self.assertEqual(captured, {"rows": 10, "cols": 20})


if __name__ == "__main__":
    unittest.main()

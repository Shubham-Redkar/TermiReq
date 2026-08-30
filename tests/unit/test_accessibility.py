"""Unit tests for the accessibility adapter layer (Task 1)."""

from __future__ import annotations

import io
import unittest

from src.accessibility import (
    NullAdapter,
    SpeechAdapter,
    StreamAdapter,
    get_adapter,
    summarize_diff,
)
from src.config import AccessibilityConfig
from src.contracts import AccessibilityAnnouncement, Cell, CellChange, DiffResult


def _announcement(text="hi", kind="info", priority="polite"):
    return AccessibilityAnnouncement(text=text, kind=kind, priority=priority)


class TestNullAdapter(unittest.TestCase):
    def test_announce_is_noop(self) -> None:
        adapter = NullAdapter()
        adapter.announce(_announcement())  # must not raise
        self.assertFalse(adapter.available)


class TestStreamAdapter(unittest.TestCase):
    def test_writes_line_with_kind(self) -> None:
        buf = io.StringIO()
        adapter = StreamAdapter(buf)
        adapter.announce(_announcement("Command ls succeeded.", kind="command_finished"))
        self.assertEqual(buf.getvalue(), "[command_finished] Command ls succeeded.\n")

    def test_assertive_prefixed_with_bang(self) -> None:
        buf = io.StringIO()
        StreamAdapter(buf).announce(_announcement("boom", kind="bell", priority="assertive"))
        self.assertTrue(buf.getvalue().startswith("![bell]"))

    def test_batch_announce_all(self) -> None:
        buf = io.StringIO()
        StreamAdapter(buf).announce_all([_announcement("a"), _announcement("b")])
        self.assertEqual(buf.getvalue().count("\n"), 2)

    def test_write_to_closed_stream_does_not_raise(self) -> None:
        buf = io.StringIO()
        buf.close()
        StreamAdapter(buf).announce(_announcement())  # swallowed


class TestSpeechAdapter(unittest.TestCase):
    def _recording_runner(self):
        calls = []

        def runner(cmd, env=None):
            calls.append((list(cmd), env))

        return calls, runner

    def test_macos_uses_say(self) -> None:
        calls, runner = self._recording_runner()
        adapter = SpeechAdapter(system="Darwin", runner=runner)
        adapter.announce(_announcement("hello"))
        self.assertEqual(calls[0][0], ["say", "hello"])

    def test_macos_rate_flag(self) -> None:
        adapter = SpeechAdapter(system="Darwin", speech_rate=200)
        cmd, _ = adapter.build_command("hi")
        self.assertEqual(cmd, ["say", "-r", "200", "hi"])

    def test_linux_prefers_spd_say(self) -> None:
        adapter = SpeechAdapter(system="Linux")
        cmd, _ = adapter.build_command("hi")
        self.assertEqual(cmd[0], "spd-say")

    def test_linux_falls_back_to_espeak(self) -> None:
        # First candidate (spd-say) raises FileNotFoundError -> espeak is used.
        attempted = []

        def runner(cmd, env=None):
            attempted.append(cmd[0])
            if cmd[0] == "spd-say":
                raise FileNotFoundError

        adapter = SpeechAdapter(system="Linux", runner=runner)
        adapter.announce(_announcement("hi"))
        self.assertEqual(attempted, ["spd-say", "espeak"])

    def test_windows_uses_powershell_with_env_text(self) -> None:
        adapter = SpeechAdapter(system="Windows")
        cmd, env = adapter.build_command("changed 3 cells")
        self.assertEqual(cmd[0], "powershell")
        self.assertIn("System.Speech", cmd[-1])
        self.assertEqual(env["TTYDIFF_TEXT"], "changed 3 cells")

    def test_unknown_platform_yields_no_command(self) -> None:
        adapter = SpeechAdapter(system="Plan9")
        cmd, _ = adapter.build_command("hi")
        self.assertIsNone(cmd)
        self.assertFalse(adapter.available)


class TestGetAdapter(unittest.TestCase):
    def test_disabled_returns_null(self) -> None:
        cfg = AccessibilityConfig(enabled=False, backend="speech")
        self.assertIsInstance(get_adapter(cfg), NullAdapter)

    def test_auto_on_desktop_is_speech(self) -> None:
        cfg = AccessibilityConfig(enabled=True, backend="auto")
        self.assertIsInstance(get_adapter(cfg, system="Linux"), SpeechAdapter)

    def test_auto_on_unknown_is_null(self) -> None:
        cfg = AccessibilityConfig(enabled=True, backend="auto")
        self.assertIsInstance(get_adapter(cfg, system="Solaris"), NullAdapter)

    def test_stream_backend(self) -> None:
        cfg = AccessibilityConfig(enabled=True, backend="stream")
        buf = io.StringIO()
        self.assertIsInstance(get_adapter(cfg, stream=buf), StreamAdapter)

    def test_unknown_backend_is_null(self) -> None:
        cfg = AccessibilityConfig(enabled=True, backend="bogus")
        self.assertIsInstance(get_adapter(cfg), NullAdapter)


class TestSummarizeDiff(unittest.TestCase):
    def _diff(self, changes=0, scrolled=False):
        cell_changes = [
            CellChange(row=i, col=0, old=Cell(" "), new=Cell("x"))
            for i in range(changes)
        ]
        return DiffResult(
            changes=cell_changes,
            cursor_moved=False,
            new_cursor=(0, 0),
            scrolled=scrolled,
            scroll_direction="up" if scrolled else None,
            scroll_amount=2 if scrolled else 0,
        )

    def test_success_summary(self) -> None:
        out = summarize_diff("ls", 0, self._diff(changes=3))
        self.assertEqual(len(out), 1)
        self.assertIn("succeeded", out[0].text)
        self.assertIn("3 cells changed", out[0].text)
        self.assertEqual(out[0].priority, "polite")

    def test_failure_is_assertive(self) -> None:
        out = summarize_diff("bad", 1, self._diff(changes=0))
        self.assertIn("failed with exit code 1", out[0].text)
        self.assertEqual(out[0].priority, "assertive")

    def test_no_changes_message(self) -> None:
        out = summarize_diff("true", 0, self._diff(changes=0))
        self.assertIn("No visible changes", out[0].text)

    def test_scroll_mentioned(self) -> None:
        out = summarize_diff("cat f", 0, self._diff(changes=1, scrolled=True))
        self.assertIn("scrolled up by 2 lines", out[0].text)

    def test_singular_cell(self) -> None:
        out = summarize_diff("x", 0, self._diff(changes=1))
        self.assertIn("1 cell changed", out[0].text)

    def test_detailed_verbosity_lists_cells(self) -> None:
        out = summarize_diff("x", 0, self._diff(changes=2), verbosity="detailed")
        self.assertEqual(len(out), 3)  # 1 summary + 2 cell changes
        self.assertEqual(out[1].kind, "cell_change")


if __name__ == "__main__":
    unittest.main()

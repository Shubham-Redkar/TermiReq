"""Accessibility integration (Task 1) — a zero-dependency adapter layer.

Goal: feed the parsed/diffed screen state to assistive technology so a
low-vision or blind user learns *what changed* after each command, without the
project taking on any third-party dependency.

## Design

A single common interface, :class:`AccessibilityAdapter`, with pluggable
backends. The rest of the program only ever talks to that interface, so new
backends (including native OS bridges) can be dropped in later:

    * :class:`NullAdapter`   — discards everything (default / unsupported).
    * :class:`StreamAdapter` — writes plain-text announcements to a file or
      stream. This is the machine-readable "data layer" a dedicated screen
      reader or monitoring tool can tail (`tail -f`) and re-speak.
    * :class:`SpeechAdapter` — speaks announcements through the operating
      system's own speech service using only stdlib ``subprocess``.

## Why not bind UIA / NSAccessibility / AT-SPI directly?

Those native accessibility APIs are the "right" long-term integration, but each
requires a third-party binding — ``comtypes``/``pywinauto`` (Windows UIA),
``pyobjc`` (macOS ``NSAccessibility``), or ``pyatspi``/``PyGObject`` (Linux
AT-SPI). Adding any of them would break this project's zero-dependency
guarantee (see STDLIB.md).

Instead, :class:`SpeechAdapter` routes through the *same* OS speech services
those screen readers already use, with zero extra packages:

    * Windows  -> PowerShell ``System.Speech`` (SAPI) — the engine behind
      Narrator; NVDA users can also read the :class:`StreamAdapter` output.
    * macOS    -> ``say`` — the VoiceOver speech engine.
    * Linux    -> ``spd-say`` (speech-dispatcher, which Orca/AT-SPI drive) with
      an ``espeak`` fallback.

The common interface is the seam: a future native-provider backend that *does*
depend on ``pyatspi``/``comtypes`` can implement :class:`AccessibilityAdapter`
and be selected via config without touching any caller.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from typing import Callable, Iterable, List, Sequence, TextIO

from .config import AccessibilityConfig
from .contracts import AccessibilityAnnouncement, DiffResult
from .logger import get_logger

logger = get_logger(__name__)


# Low-level command runner signature: ``runner(argv, env=None)`` (injectable
# for tests). Raising FileNotFoundError signals "engine missing, try fallback".
Runner = Callable[..., None]


class AccessibilityAdapter:
    """Common interface for delivering announcements to assistive technology.

    Backends override :meth:`announce`. Callers should always go through
    :meth:`announce_all` / :meth:`announce` and never assume a concrete type.
    """

    #: True when this backend can actually convey output (used for messaging).
    available: bool = True

    def announce(self, announcement: AccessibilityAnnouncement) -> None:
        """Deliver a single announcement. Base implementation is a no-op."""

    def announce_all(
        self, announcements: Iterable[AccessibilityAnnouncement]
    ) -> None:
        """Deliver a batch of announcements in order."""
        for announcement in announcements:
            self.announce(announcement)

    def close(self) -> None:
        """Release any resources (files, handles). Safe to call twice."""


class NullAdapter(AccessibilityAdapter):
    """Discards every announcement. Used when accessibility is disabled."""

    available = False


class StreamAdapter(AccessibilityAdapter):
    """Write announcements as plain text lines to a stream or file.

    Each line is ``[kind] text`` (assertive messages are prefixed with ``!``),
    which a screen reader or a simple ``tail -f`` consumer can read. This is the
    zero-dependency "data layer" hand-off point for external AT tooling.
    """

    def __init__(
        self,
        stream: TextIO | None = None,
        *,
        path: str | None = None,
    ) -> None:
        self._owns_stream = False
        if stream is not None:
            self._stream: TextIO = stream
        elif path is not None:
            self._stream = open(path, "a", encoding="utf-8")
            self._owns_stream = True
        else:
            self._stream = sys.stderr

    def announce(self, announcement: AccessibilityAnnouncement) -> None:
        marker = "!" if announcement.priority == "assertive" else ""
        line = f"{marker}[{announcement.kind}] {announcement.text}"
        try:
            self._stream.write(line + "\n")
            self._stream.flush()
        except (ValueError, OSError):
            # Stream closed underneath us — degrade silently rather than crash
            # the diff pipeline over an accessibility side-channel.
            pass

    def close(self) -> None:
        if self._owns_stream:
            try:
                self._stream.close()
            except OSError:
                pass
            self._owns_stream = False


def _default_runner(cmd: Sequence[str], env: dict | None = None) -> None:
    """Run ``cmd``. Lets ``FileNotFoundError`` propagate (so the caller can try
    a fallback engine) but swallows other spawn/runtime errors so a flaky
    speech side-channel never crashes the diff pipeline.
    """
    try:
        subprocess.run(
            list(cmd),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=env,
        )
    except FileNotFoundError:
        raise
    except OSError:
        pass


class SpeechAdapter(AccessibilityAdapter):
    """Speak announcements through the operating system's speech service.

    Uses only stdlib ``subprocess`` — no TTS package. Arguments are always
    passed as a list (never ``shell=True``) so announcement text can never be
    interpreted as a shell command.
    """

    def __init__(
        self,
        *,
        system: str | None = None,
        speech_rate: int | None = None,
        runner: Callable[..., None] | None = None,
    ) -> None:
        self._system = system or platform.system()
        self._rate = speech_rate
        self._run = runner or _default_runner
        self.available = self._system in ("Darwin", "Linux", "Windows")

    def build_command(
        self, text: str
    ) -> tuple[list[str] | None, dict | None]:
        """Return the primary ``(argv, env)`` for speaking ``text``.

        Kept for testability and callers that only need one command; the full
        ordered candidate list (with Linux fallback) is :meth:`candidate_commands`.
        Returns ``(None, None)`` on an unsupported platform.
        """
        candidates = self.candidate_commands(text)
        return candidates[0] if candidates else (None, None)

    def candidate_commands(
        self, text: str
    ) -> list[tuple[list[str], dict | None]]:
        """Ordered speech commands to attempt; later entries are fallbacks."""
        if self._system == "Darwin":
            cmd = ["say"]
            if self._rate:
                cmd += ["-r", str(self._rate)]
            cmd.append(text)
            return [(cmd, None)]

        if self._system == "Linux":
            # spd-say drives speech-dispatcher (what Orca/AT-SPI use); espeak is
            # the fallback when speech-dispatcher is not installed.
            spd = ["spd-say", "-w"]
            espeak = ["espeak"]
            if self._rate:
                spd += ["-r", str(_clamp(self._rate - 175, -100, 100))]
                espeak += ["-s", str(self._rate)]
            spd.append(text)
            espeak.append(text)
            return [(spd, None), (espeak, None)]

        if self._system == "Windows":
            # PowerShell + System.Speech (SAPI). Pass text/rate via the
            # environment so no quoting of the announcement is ever required.
            script = (
                "Add-Type -AssemblyName System.Speech;"
                "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                "if ($env:TTYDIFF_RATE) { $s.Rate = [int]$env:TTYDIFF_RATE };"
                "$s.Speak($env:TTYDIFF_TEXT)"
            )
            env = dict(os.environ)
            env["TTYDIFF_TEXT"] = text
            if self._rate is not None:
                # SAPI rate is -10..10; map a WPM-ish value into that band.
                env["TTYDIFF_RATE"] = str(_clamp((self._rate - 175) // 15, -10, 10))
            return [(["powershell", "-NoProfile", "-Command", script], env)]

        return []

    def announce(self, announcement: AccessibilityAnnouncement) -> None:
        for cmd, env in self.candidate_commands(announcement.text):
            try:
                self._run(cmd, env)
                return
            except FileNotFoundError:
                continue  # Engine not installed — try the next candidate.


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


# --------------------------------------------------------------------------- #
# Factory + diff summarization
# --------------------------------------------------------------------------- #

# Platforms where speaking is a sensible default for backend="auto".
_DESKTOP_SYSTEMS = ("Darwin", "Linux", "Windows")


def get_adapter(
    config: AccessibilityConfig,
    *,
    system: str | None = None,
    stream: TextIO | None = None,
) -> AccessibilityAdapter:
    """Build the adapter described by ``config``.

    ``backend`` values: ``auto`` (speech on a desktop OS, else null), ``speech``,
    ``stream``, or ``null``. A disabled config always yields :class:`NullAdapter`.
    """
    if not config.enabled:
        return NullAdapter()

    sysname = system or platform.system()
    backend = config.backend

    if backend == "auto":
        backend = "speech" if sysname in _DESKTOP_SYSTEMS else "null"

    if backend == "null":
        logger.debug("a11y backend=null")
        return NullAdapter()
    if backend == "stream":
        logger.debug("a11y backend=stream path=%s", config.stream_path)
        return StreamAdapter(stream, path=config.stream_path)
    if backend == "speech":
        logger.debug("a11y backend=speech system=%s rate=%s", sysname, config.speech_rate)
        return SpeechAdapter(system=sysname, speech_rate=config.speech_rate)
    # Unknown backend name — be safe, announce nothing.
    logger.warning("unknown a11y backend %r; using null", backend)
    return NullAdapter()


def _describe_cursor(diff: DiffResult) -> str:
    row, col = diff.new_cursor
    return f"cursor at row {row + 1}, column {col + 1}"


def summarize_diff(
    command: str,
    exit_code: int,
    diff: DiffResult,
    *,
    verbosity: str = "summary",
) -> List[AccessibilityAnnouncement]:
    """Turn a :class:`DiffResult` into ordered accessibility announcements.

    ``summary`` gives one spoken sentence per command; ``detailed`` additionally
    reads each changed cell (useful for a text/stream backend, verbose aloud).
    """
    announcements: List[AccessibilityAnnouncement] = []

    status = "succeeded" if exit_code == 0 else f"failed with exit code {exit_code}"
    n = len(diff.changes)
    parts = [f"Command {command} {status}."]
    if diff.scrolled:
        parts.append(
            f"Screen scrolled {diff.scroll_direction} by {diff.scroll_amount} lines."
        )
    if n == 0 and not diff.scrolled:
        parts.append("No visible changes.")
    else:
        parts.append(f"{n} cell{'s' if n != 1 else ''} changed.")

    announcements.append(
        AccessibilityAnnouncement(
            text=" ".join(parts),
            kind="command_finished",
            priority="polite" if exit_code == 0 else "assertive",
            command=command,
        )
    )

    if verbosity == "detailed" and diff.changes:
        for change in diff.changes:
            old = change.old.char if change.old.char != " " else "blank"
            new = change.new.char if change.new.char != " " else "blank"
            announcements.append(
                AccessibilityAnnouncement(
                    text=(
                        f"Row {change.row + 1} column {change.col + 1}: "
                        f"{old} became {new}."
                    ),
                    kind="cell_change",
                    priority="polite",
                    command=command,
                )
            )

    return announcements

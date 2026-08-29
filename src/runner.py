"""PTY command runner (T1/T1b).

Spawns shell commands through a pseudo-terminal so programs emit full ANSI
output instead of plain-text pipe mode. Runs commands strictly sequentially.
"""

from __future__ import annotations

import errno
import os
import select
import signal
import subprocess
import sys
import time
from collections.abc import Generator
from typing import Callable

from src.contracts import CommandChunk, CommandFinished, RunnerEvent

if sys.platform != "win32":
    import fcntl
    import struct
    import termios

# Exit code used when a command is interrupted (Ctrl-C) or skipped.
INTERRUPTED_EXIT_CODE = 130


def pty_supported() -> bool:
    """Return True when the platform can allocate a pseudo-terminal."""
    if sys.platform == "win32":
        return False
    try:
        import pty

        master_fd, slave_fd = pty.openpty()
        os.close(master_fd)
        os.close(slave_fd)
        return True
    except (AttributeError, OSError):
        return False


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    if sys.platform == "win32":
        return
    winsize = struct.pack("HHHH", rows, cols, 0, 0)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, winsize)


def _read_until_done(
    master_fd: int,
    proc: subprocess.Popen[bytes],
    timeout: float | None,
) -> tuple[bytes, int, bool]:
    """Read PTY output until the process exits or timeout fires."""
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout if timeout is not None else None
    timed_out = False

    while True:
        if deadline is not None and time.monotonic() >= deadline:
            timed_out = True
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            proc.wait(timeout=2)
            break

        poll_timeout = 0.1 if deadline is not None else None
        try:
            readable, _, _ = select.select([master_fd], [], [], poll_timeout)
        except (OSError, ValueError):
            break

        if master_fd in readable:
            try:
                data = os.read(master_fd, 4096)
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    break
                raise
            if not data:
                break
            chunks.append(data)

        if proc.poll() is not None:
            _drain_master(master_fd, chunks)
            break

    exit_code = proc.wait() if proc.poll() is None else proc.returncode
    return b"".join(chunks), exit_code if exit_code is not None else -1, timed_out


def _drain_master(master_fd: int, chunks: list[bytes]) -> None:
    while True:
        try:
            readable, _, _ = select.select([master_fd], [], [], 0)
        except (OSError, ValueError):
            break
        if master_fd not in readable:
            break
        try:
            data = os.read(master_fd, 4096)
        except OSError:
            break
        if not data:
            break
        chunks.append(data)


def _run_single_command_pty(
    command: str,
    command_index: int,
    *,
    timeout: float | None,
    rows: int,
    cols: int,
) -> Generator[RunnerEvent, None, None]:
    import pty

    master_fd, slave_fd = pty.openpty()
    _set_winsize(master_fd, rows, cols)
    _set_winsize(slave_fd, rows, cols)

    proc = subprocess.Popen(
        command,
        shell=True,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
        preexec_fn=os.setsid,
    )
    os.close(slave_fd)

    try:
        output, exit_code, timed_out = _read_until_done(master_fd, proc, timeout)
        yield CommandChunk(command=command, data=output, command_index=command_index)
        yield CommandFinished(
            command=command,
            command_index=command_index,
            exit_code=exit_code,
            timed_out=timed_out,
        )
    finally:
        os.close(master_fd)
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            proc.wait(timeout=2)


def _run_single_command_subprocess(
    command: str,
    command_index: int,
    *,
    timeout: float | None,
    rows: int = 24,
    cols: int = 80,
) -> Generator[RunnerEvent, None, None]:
    """Fallback when PTY is unavailable (e.g. Windows dev environments)."""
    timed_out = False
    try:
        completed = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            timeout=timeout,
        )
        output = completed.stdout + completed.stderr
        exit_code = completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = (exc.stdout or b"") + (exc.stderr or b"")
        exit_code = -1

    yield CommandChunk(command=command, data=output, command_index=command_index)
    yield CommandFinished(
        command=command,
        command_index=command_index,
        exit_code=exit_code,
        timed_out=timed_out,
    )


def run_commands(
    commands: list[str],
    *,
    timeout: float | None = None,
    rows: int = 24,
    cols: int = 80,
    use_pty: bool | None = None,
    runner_fn: Callable[..., Generator[RunnerEvent, None, None]] | None = None,
) -> Generator[RunnerEvent, None, None]:
    """Run commands sequentially, yielding output chunks and finish events.

    Each command must finish (or be skipped/timed out) before the next starts.
    Ctrl-C during a command kills that command and continues with the next one.
    """
    if not commands:
        return

    use_real_pty = pty_supported() if use_pty is None else use_pty
    single_runner = runner_fn or (
        _run_single_command_pty if use_real_pty else _run_single_command_subprocess
    )

    for index, command in enumerate(commands):
        try:
            yield from single_runner(
                command,
                index,
                timeout=timeout,
                rows=rows,
                cols=cols,
            )
        except KeyboardInterrupt:
            yield CommandChunk(command=command, data=b"", command_index=index)
            yield CommandFinished(
                command=command,
                command_index=index,
                exit_code=INTERRUPTED_EXIT_CODE,
                skipped=True,
            )

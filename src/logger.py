"""Logging & debugging tools (Task 9) — zero-dependency diagnostics.

A single place to configure the process-wide logger using only the stdlib
``logging`` module. Everything goes to **stderr** so the diff/JSON on stdout
stays clean and pipeable.

Verbosity levels (lowest to highest):
    default (WARNING)  — silent on the happy path; warnings/errors only.
    ``--verbose``      — INFO: one line per pipeline step (config found,
                         geometry detected, command started/finished, etc.).
    ``--debug``        — DEBUG: per-event / per-chunk detail for debugging
                         parser or diff issues.

Any module can grab a logger with :func:`get_logger`; it is pre-named
``ttydiff.<module>`` so log lines carry the source module for free.

Log handler follows the *current* ``sys.stderr`` on every emit, so when a
caller wraps a run in :func:`contextlib.redirect_stderr` the log lines land in
the captured buffer instead of the stderr captured at startup.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Optional

#: Valid level names accepted by ``--log-level`` / ``TTYDIFF_LOG_LEVEL``.
_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
}

#: Set once by :func:`configure_logging`; lets CLI flag overrides win over
#: an environment value without re-configuring handlers.
_configured: bool = False


class _CurrentStderrHandler(logging.Handler):
    """Writes every record to whatever ``sys.stderr`` currently points at.

    Unlike a plain :class:`logging.StreamHandler`, which pins its stream once at
    construction, this re-reads ``sys.stderr`` on each ``emit`` — so
    ``contextlib.redirect_stderr`` captures the logs too.
    """

    terminator = "\n"

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            sys.stderr.write(msg + self.terminator)
            sys.stderr.flush()
        except Exception:
            self.handleError(record)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger named ``ttydiff.<name>``.

    Namespace is local to this project so third-party log noise never mixes
    in; each module passes its ``__name__`` and gets ``ttydiff.src.parser`` etc.
    """
    prefix = "ttydiff"
    if name == prefix or name.startswith(prefix + "."):
        full = name
    else:
        full = f"{prefix}.{name}"
    return logging.getLogger(full)


def _resolve_level(verbose: bool, debug: bool, env_level: Optional[str]) -> int:
    """Combine CLI flags and env override into a logging level int.

    Precedence: ``--debug`` > ``--verbose`` > ``TTYDIFF_LOG_LEVEL`` env >
    default WARNING. An unrecognized env value falls back to WARNING rather
    than crashing the tool.
    """
    if debug:
        return logging.DEBUG
    if verbose:
        return logging.INFO
    if env_level:
        return _LEVELS.get(env_level.strip().lower(), logging.WARNING)
    return logging.WARNING


def configure_logging(
    *,
    verbose: bool = False,
    debug: bool = False,
) -> logging.Logger:
    """Install the root ``ttydiff`` logger and return it.

    Idempotent: reconfiguring just adjusts the level, it never stacks
    duplicate handlers. Safe to call from tests repeatedly.
    """
    root = logging.getLogger("ttydiff")
    root.setLevel(_resolve_level(verbose, debug, os.environ.get("TTYDIFF_LOG_LEVEL")))

    global _configured
    if not _configured:
        handler = _CurrentStderrHandler()
        handler.setFormatter(
            logging.Formatter(
                "[%(levelname)s] %(name)s: %(message)s",
            )
        )
        root.addHandler(handler)
        _configured = True

    return root
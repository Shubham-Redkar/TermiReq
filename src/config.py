"""Configuration file support (zero-dependency).

Loads user preferences from a ``config.toml`` file and layers environment
variable overrides on top. TOML parsing uses the standard library ``tomllib``
module (Python 3.11+); if it is unavailable the loader silently falls back to
built-in defaults so the tool never hard-crashes on an old interpreter — in
keeping with the project's zero-third-party-dependency guarantee (see
STDLIB.md).

Precedence (lowest to highest):
    1. Built-in defaults (:func:`default_config`).
    2. Values from the first ``config.toml`` found on the search path.
    3. Environment variable overrides (``TTYDIFF_*`` and ``NO_COLOR``).

An explicit path (from ``--config`` / ``$TTYDIFF_CONFIG``) always wins the
search and, if it does not exist, raises ``FileNotFoundError`` so typos are not
silently ignored.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .logger import get_logger

try:  # Python 3.11+ ships tomllib in the stdlib.
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised only on <3.11
    tomllib = None  # type: ignore[assignment]

logger = get_logger(__name__)


# Config file names looked for in the current working directory.
_LOCAL_NAMES = ("config.toml", "ttydiff.toml")


@dataclass
class TerminalConfig:
    """Virtual/PTY geometry. ``None`` means auto-detect from the real terminal."""
    rows: int | None = None
    cols: int | None = None


@dataclass
class ColorConfig:
    """Diff coloring. ``enabled=None`` means decide automatically (tty + NO_COLOR)."""
    enabled: bool | None = None
    theme: str = "default"


@dataclass
class AccessibilityConfig:
    """Accessibility adapter settings (see :mod:`src.accessibility`)."""
    enabled: bool = False
    backend: str = "auto"          # auto | speech | stream | null
    speech_rate: int | None = None
    stream_path: str | None = None
    verbosity: str = "summary"     # summary | detailed


@dataclass
class Config:
    """The fully-resolved configuration for a single CLI invocation."""
    terminal: TerminalConfig = field(default_factory=TerminalConfig)
    color: ColorConfig = field(default_factory=ColorConfig)
    accessibility: AccessibilityConfig = field(default_factory=AccessibilityConfig)


def default_config() -> Config:
    """Return a fresh :class:`Config` populated entirely with defaults."""
    return Config()


def _truthy(value: str) -> bool:
    """Interpret a string env value as a boolean the forgiving way."""
    return value.strip().lower() in ("1", "true", "yes", "on")


def _as_int(value: object) -> int | None:
    """Coerce a TOML/env value to int, or None if it cannot be parsed."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def candidate_paths(env: Mapping[str, str] | None = None) -> list[Path]:
    """Return the config file locations to try, in priority order.

    Order: an explicit ``$TTYDIFF_CONFIG`` first, then ``./config.toml`` /
    ``./ttydiff.toml``, then the XDG user config location.
    """
    env = os.environ if env is None else env
    paths: list[Path] = []

    explicit = env.get("TTYDIFF_CONFIG")
    if explicit:
        paths.append(Path(explicit))

    for name in _LOCAL_NAMES:
        paths.append(Path.cwd() / name)

    xdg = env.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    paths.append(base / "ttydiff" / "config.toml")

    return paths


def _find_config_file(
    path: str | None, env: Mapping[str, str]
) -> Path | None:
    """Resolve which config file to read (or None if there is none)."""
    if path is not None:
        p = Path(path)
        if not p.is_file():
            raise FileNotFoundError(f"config file not found: {path}")
        return p
    for candidate in candidate_paths(env):
        if candidate.is_file():
            return candidate
    return None


def _parse_toml(path: Path) -> dict:
    """Read a TOML file into a dict, tolerating a missing tomllib gracefully."""
    if tomllib is None:  # pragma: no cover - only on <3.11
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _merge_file(config: Config, data: dict) -> None:
    """Overlay parsed TOML ``data`` onto ``config`` in place.

    Unknown keys/sections are ignored so a newer config file never breaks an
    older binary; missing keys keep their default.
    """
    term = data.get("terminal", {})
    if isinstance(term, dict):
        if "rows" in term:
            config.terminal.rows = _as_int(term["rows"])
        if "cols" in term:
            config.terminal.cols = _as_int(term["cols"])

    color = data.get("color", {})
    if isinstance(color, dict):
        if "enabled" in color:
            config.color.enabled = bool(color["enabled"])
        if "theme" in color:
            config.color.theme = str(color["theme"])

    a11y = data.get("accessibility", {})
    if isinstance(a11y, dict):
        if "enabled" in a11y:
            config.accessibility.enabled = bool(a11y["enabled"])
        if "backend" in a11y:
            config.accessibility.backend = str(a11y["backend"])
        if "speech_rate" in a11y:
            config.accessibility.speech_rate = _as_int(a11y["speech_rate"])
        if "stream_path" in a11y:
            config.accessibility.stream_path = str(a11y["stream_path"])
        if "verbosity" in a11y:
            config.accessibility.verbosity = str(a11y["verbosity"])


def _apply_env(config: Config, env: Mapping[str, str]) -> None:
    """Layer ``TTYDIFF_*`` (and ``NO_COLOR``) overrides onto ``config``."""
    if "TTYDIFF_ROWS" in env:
        config.terminal.rows = _as_int(env["TTYDIFF_ROWS"])
    if "TTYDIFF_COLS" in env:
        config.terminal.cols = _as_int(env["TTYDIFF_COLS"])

    # NO_COLOR (https://no-color.org) forces color off regardless of value.
    if env.get("NO_COLOR"):
        config.color.enabled = False
    if "TTYDIFF_COLOR" in env:
        config.color.enabled = _truthy(env["TTYDIFF_COLOR"])
    if env.get("TTYDIFF_THEME"):
        config.color.theme = env["TTYDIFF_THEME"]

    if "TTYDIFF_ACCESSIBILITY" in env:
        config.accessibility.enabled = _truthy(env["TTYDIFF_ACCESSIBILITY"])
    if env.get("TTYDIFF_A11Y_BACKEND"):
        config.accessibility.backend = env["TTYDIFF_A11Y_BACKEND"]
    if "TTYDIFF_SPEECH_RATE" in env:
        config.accessibility.speech_rate = _as_int(env["TTYDIFF_SPEECH_RATE"])
    if env.get("TTYDIFF_A11Y_STREAM"):
        config.accessibility.stream_path = env["TTYDIFF_A11Y_STREAM"]


def load_config(
    path: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> Config:
    """Load configuration from ``path`` (or the search path) plus env overrides.

    Raises ``FileNotFoundError`` only when an explicit ``path`` is given and
    does not exist. A missing file on the implicit search path is not an error.
    """
    env = os.environ if env is None else env
    config = default_config()

    config_file = _find_config_file(path, env)
    if config_file is not None:
        logger.info("loading config from %s", config_file)
        try:
            _merge_file(config, _parse_toml(config_file))
        except (OSError, ValueError):
            # A malformed or unreadable config must not take down the tool;
            # fall through with whatever defaults/partial values we have.
            logger.warning("could not parse config %s; using defaults", config_file)
    else:
        logger.debug("no config file found; using built-in defaults")

    _apply_env(config, env)
    return config

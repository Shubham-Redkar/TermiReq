"""Unit tests for configuration loading (Task 4)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from src.config import (
    Config,
    candidate_paths,
    default_config,
    load_config,
)


class TestDefaults(unittest.TestCase):
    def test_defaults_are_conservative(self) -> None:
        cfg = default_config()
        self.assertIsNone(cfg.terminal.rows)
        self.assertIsNone(cfg.terminal.cols)
        self.assertIsNone(cfg.color.enabled)
        self.assertEqual(cfg.color.theme, "default")
        self.assertFalse(cfg.accessibility.enabled)
        self.assertEqual(cfg.accessibility.backend, "auto")

    def test_no_file_no_env_returns_defaults(self) -> None:
        cfg = load_config(env={})
        self.assertEqual(cfg, Config())


class TestFileLoading(unittest.TestCase):
    def _write(self, text: str) -> str:
        tmp = tempfile.NamedTemporaryFile(
            "w", suffix=".toml", delete=False, encoding="utf-8"
        )
        tmp.write(text)
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return tmp.name

    def test_reads_all_sections(self) -> None:
        path = self._write(
            """
            [terminal]
            rows = 40
            cols = 120

            [color]
            enabled = true
            theme = "solarized"

            [accessibility]
            enabled = true
            backend = "stream"
            speech_rate = 200
            stream_path = "/tmp/out.log"
            verbosity = "detailed"
            """
        )
        cfg = load_config(path, env={})
        self.assertEqual(cfg.terminal.rows, 40)
        self.assertEqual(cfg.terminal.cols, 120)
        self.assertTrue(cfg.color.enabled)
        self.assertEqual(cfg.color.theme, "solarized")
        self.assertTrue(cfg.accessibility.enabled)
        self.assertEqual(cfg.accessibility.backend, "stream")
        self.assertEqual(cfg.accessibility.speech_rate, 200)
        self.assertEqual(cfg.accessibility.stream_path, "/tmp/out.log")
        self.assertEqual(cfg.accessibility.verbosity, "detailed")

    def test_partial_file_keeps_defaults(self) -> None:
        path = self._write("[color]\ntheme = \"nord\"\n")
        cfg = load_config(path, env={})
        self.assertEqual(cfg.color.theme, "nord")
        self.assertIsNone(cfg.terminal.rows)  # untouched

    def test_unknown_keys_ignored(self) -> None:
        path = self._write("[wat]\nfoo = 1\n[terminal]\nrows = 10\nbogus = 2\n")
        cfg = load_config(path, env={})
        self.assertEqual(cfg.terminal.rows, 10)

    def test_missing_explicit_path_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_config("/no/such/config.toml", env={})

    def test_malformed_toml_falls_back_gracefully(self) -> None:
        path = self._write("this is = = not valid toml [[[")
        cfg = load_config(path, env={})
        self.assertEqual(cfg, Config())


class TestEnvOverrides(unittest.TestCase):
    def test_env_overrides_file(self) -> None:
        cfg = load_config(
            env={"TTYDIFF_ROWS": "50", "TTYDIFF_COLS": "100"}
        )
        self.assertEqual(cfg.terminal.rows, 50)
        self.assertEqual(cfg.terminal.cols, 100)

    def test_no_color_forces_color_off(self) -> None:
        cfg = load_config(env={"NO_COLOR": "1"})
        self.assertFalse(cfg.color.enabled)

    def test_ttydiff_color_toggle(self) -> None:
        self.assertTrue(load_config(env={"TTYDIFF_COLOR": "yes"}).color.enabled)
        self.assertFalse(load_config(env={"TTYDIFF_COLOR": "0"}).color.enabled)

    def test_theme_env(self) -> None:
        cfg = load_config(env={"TTYDIFF_THEME": "dracula"})
        self.assertEqual(cfg.color.theme, "dracula")

    def test_accessibility_env(self) -> None:
        cfg = load_config(
            env={
                "TTYDIFF_ACCESSIBILITY": "on",
                "TTYDIFF_A11Y_BACKEND": "speech",
                "TTYDIFF_SPEECH_RATE": "150",
            }
        )
        self.assertTrue(cfg.accessibility.enabled)
        self.assertEqual(cfg.accessibility.backend, "speech")
        self.assertEqual(cfg.accessibility.speech_rate, 150)

    def test_bad_int_env_becomes_none(self) -> None:
        cfg = load_config(env={"TTYDIFF_ROWS": "notanumber"})
        self.assertIsNone(cfg.terminal.rows)


class TestCandidatePaths(unittest.TestCase):
    def test_explicit_env_path_is_first(self) -> None:
        paths = candidate_paths(env={"TTYDIFF_CONFIG": "/etc/ttydiff.toml"})
        self.assertEqual(paths[0], Path("/etc/ttydiff.toml"))

    def test_xdg_config_home_respected(self) -> None:
        paths = candidate_paths(env={"XDG_CONFIG_HOME": "/xdg"})
        self.assertIn(Path("/xdg/ttydiff/config.toml"), paths)


if __name__ == "__main__":
    unittest.main()

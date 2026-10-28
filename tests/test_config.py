"""Configuration validation tests."""

from __future__ import unicode_literals

import os
import unittest

from truecorp_core.logging.config import (
    LoggingConfigError,
    normalize_logging_config,
)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.base_dir = os.path.abspath("/tmp/truecorp_cfg_test")

    def test_valid_config_defaults(self):
        cfg = normalize_logging_config({}, base_dir=self.base_dir)
        self.assertEqual(cfg["level"], "INFO")
        self.assertFalse(cfg["console"]["enabled"])
        self.assertFalse(cfg["rotation"]["enabled"])
        self.assertEqual(cfg["rotation"]["interval_days"], 7)

    def test_invalid_level(self):
        with self.assertRaises(LoggingConfigError):
            normalize_logging_config({"level": "VERBOSE"}, base_dir=self.base_dir)

    def test_invalid_interval_days(self):
        with self.assertRaises(LoggingConfigError):
            normalize_logging_config(
                {"rotation": {"enabled": True, "interval_days": 0}},
                base_dir=self.base_dir,
            )

    def test_invalid_retention_days(self):
        with self.assertRaises(LoggingConfigError):
            normalize_logging_config(
                {"retention": {"enabled": True, "days": -1}},
                base_dir=self.base_dir,
            )

    def test_invalid_compression_level(self):
        with self.assertRaises(LoggingConfigError):
            normalize_logging_config(
                {"rotation": {"compression_level": 10}},
                base_dir=self.base_dir,
            )

    def test_missing_optional_fields(self):
        cfg = normalize_logging_config(
            {"filename": "app.log", "directory": "./logs"},
            base_dir=self.base_dir,
        )
        self.assertEqual(cfg["filename"], "app.log")
        self.assertTrue(cfg["directory"].endswith("logs"))

    def test_path_traversal_filename(self):
        with self.assertRaises(LoggingConfigError):
            normalize_logging_config({"filename": "../evil.log"}, base_dir=self.base_dir)


if __name__ == "__main__":
    unittest.main()

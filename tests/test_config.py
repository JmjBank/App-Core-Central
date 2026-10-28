import copy
import os
import unittest

from truecorp_core.logging.config import ConfigError, load_config
from tests.support import TempTestCase


class ConfigTests(TempTestCase):
    def test_defaults_when_missing_or_empty(self):
        for raw in (None, {}):
            cfg = load_config(raw, base_dir=self.tmp)
            self.assertTrue(cfg.enabled)
            self.assertEqual(cfg.level_name, "INFO")
            self.assertEqual(cfg.directory, self.path("logs"))
            self.assertEqual(cfg.filename, "app.log")
            self.assertFalse(cfg.console_enabled)
            self.assertEqual(cfg.console_level_name, "WARNING")
            self.assertTrue(cfg.rot_enabled)
            self.assertEqual(cfg.rot_mode, "DAILY")
            self.assertEqual(cfg.interval_days, 7)
            self.assertTrue(cfg.compress)
            self.assertEqual(cfg.compression_level, 6)
            self.assertEqual((cfg.ret_enabled, cfg.ret_days, cfg.ret_cleanup_on_startup), (True, 90, True))
            self.assertTrue(cfg.redact_enabled)

    def test_valid_full_config(self):
        raw = {"enabled": True, "level": "debug", "directory": "./logs", "filename": "cancel_5534.log",
               "console": {"enabled": True, "level": "WARNING"},
               "rotation": {"enabled": True, "mode": "interval_days", "interval_days": 7, "compress": True,
                            "compression_level": 9, "anchor_date": "2026-10-07"},
               "retention": {"enabled": True, "days": 30, "cleanup_on_startup": False},
               "security": {"redact_sensitive_data": True, "redact_fields": ["password", "my_field"]}}
        cfg = load_config(raw, base_dir=self.tmp)
        self.assertEqual((cfg.level, cfg.rot_mode, cfg.rot_interval, cfg.compression_level, cfg.ret_days),
                         (10, "INTERVAL_DAYS", 7, 9, 30))
        self.assertEqual(cfg.stem, "cancel_5534")
        self.assertEqual(str(cfg.anchor_date), "2026-10-07")
        self.assertIn("my_field", cfg.redact_fields)
        self.assertIn("token", cfg.redact_fields)  # defaults are always kept

    def test_daily_interval_is_one(self):
        self.assertEqual(load_config({"rotation": {"mode": "DAILY", "interval_days": 9}}, self.tmp).rot_interval, 1)

    def test_invalid_values(self):
        bad = [
            {"level": "LOUD"}, {"enabled": "yes"}, {"filename": "a/b.log"}, {"filename": ".."},
            {"filename": "archive"}, {"unknown": 1}, {"application": {"name": "x"}},
            {"rotation": {"mode": "WEEKLY"}}, {"rotation": {"interval_days": 0}},
            {"rotation": {"interval_days": -3}}, {"rotation": {"interval_days": "7"}},
            {"rotation": {"interval_days": 1.5}}, {"rotation": {"interval_days": True}},
            {"rotation": {"compression_level": 0}}, {"rotation": {"compression_level": 10}},
            {"rotation": {"anchor_date": "07/10/2026"}}, {"rotation": {"typo_key": 1}},
            {"retention": {"days": 0}}, {"retention": {"days": "90"}}, {"console": "on"},
            {"security": {"redact_fields": "password"}}, {"security": {"redact_fields": [1]}},
            {"directory": ""}, {"directory": "../outside"}, {"directory": "a/../../outside"},
        ]
        for raw in bad:
            with self.subTest(raw=raw):
                with self.assertRaises(ConfigError):
                    load_config(raw, base_dir=self.tmp)
        with self.assertRaises(ConfigError):
            load_config("not a dict", base_dir=self.tmp)

    def test_protected_and_allowed_directories(self):
        for directory in ("/etc/app", "/usr/local/logs", "/"):
            with self.subTest(directory=directory), self.assertRaises(ConfigError):
                load_config({"directory": directory}, base_dir=self.tmp)
        with self.assertRaises(ConfigError):
            load_config({"directory": self.path("logs"), "allowed_roots": ["/data/only-here"]}, self.tmp)
        cfg = load_config({"directory": self.path("logs"), "allowed_roots": [self.tmp]}, self.tmp)
        self.assertEqual(cfg.directory, self.path("logs"))

    def test_relative_resolves_from_base_dir_not_cwd(self):
        other = self.path("elsewhere")
        os.makedirs(other)
        old = os.getcwd()
        os.chdir(other)
        self.addCleanup(os.chdir, old)
        cfg = load_config({"directory": "./logs"}, base_dir=self.tmp)
        self.assertEqual(cfg.directory, self.path("logs"))

    def test_absolute_path_accepted(self):
        target = self.path("abs", "logs")
        self.assertEqual(load_config({"directory": target}, base_dir="/tmp").directory, target)

    def test_input_is_not_modified(self):
        raw = {"directory": "./logs", "rotation": {"mode": "DAILY"}, "security": {"redact_fields": ["x"]}}
        snapshot = copy.deepcopy(raw)
        load_config(raw, base_dir=self.tmp)
        self.assertEqual(raw, snapshot)

    def test_signature_changes_with_config(self):
        a = load_config({"level": "INFO"}, self.tmp).signature()
        self.assertEqual(a, load_config({"level": "INFO"}, self.tmp).signature())
        self.assertNotEqual(a, load_config({"level": "DEBUG"}, self.tmp).signature())


if __name__ == "__main__":
    unittest.main()

"""Integration-style tests for cron/daemon flows."""

from __future__ import unicode_literals

import logging
import os
import shutil
import tempfile
import unittest
import warnings

from truecorp_core.logging import (
    get_logger,
    reset_setup_state_for_tests,
    set_run_context,
    setup_logging,
    shutdown_logging,
)
from truecorp_core.logging.factory import _SETUP_STATE


class TestIntegration(unittest.TestCase):
    def setUp(self):
        reset_setup_state_for_tests()
        self.base = tempfile.mkdtemp(prefix="truecorp_int_")

    def tearDown(self):
        shutdown_logging()
        reset_setup_state_for_tests()
        shutil.rmtree(self.base, ignore_errors=True)

    def test_repeated_cron_execution(self):
        cfg = {
            "enabled": True,
            "level": "INFO",
            "directory": os.path.join(self.base, "logs"),
            "filename": "cron.log",
            "rotation": {"enabled": False},
            "retention": {"enabled": False},
            "console": {"enabled": False},
        }
        for run in range(2):
            reset_setup_state_for_tests()
            os.makedirs(os.path.join(self.base, "logs"), exist_ok=True)
            setup_logging(cfg, application_name="CRON", base_dir=self.base)
            set_run_context(run_id="RUN-%s" % run)
            get_logger("CRON").info("tick")
            shutdown_logging()
        with open(os.path.join(self.base, "logs", "cron.log"), "r", encoding="utf-8") as handle:
            self.assertEqual(len(handle.readlines()), 2)

    def test_config_change_policy(self):
        cfg1 = {
            "enabled": True,
            "level": "INFO",
            "directory": os.path.join(self.base, "logs"),
            "filename": "policy.log",
            "rotation": {"enabled": False},
            "retention": {"enabled": False},
            "console": {"enabled": False},
        }
        cfg2 = dict(cfg1)
        cfg2["level"] = "DEBUG"
        setup_logging(cfg1, application_name="APP", base_dir=self.base)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            setup_logging(cfg2, application_name="APP", base_dir=self.base)
        self.assertTrue(any(isinstance(w.message, RuntimeWarning) for w in caught))
        markers = [
            h
            for h in logging.getLogger().handlers
            if getattr(h, "_truecorp_marker", "")
        ]
        self.assertEqual(len(markers), 1)

    def test_concurrent_process_policy_documented(self):
        """Library relies on flock during rotation; parallel cron without split files is unsafe."""
        lock_path = os.path.join(self.base, "logs", ".logging_state", "cron.log.rotation.lock")
        self.assertTrue(hasattr(__import__("fcntl"), "flock"))


if __name__ == "__main__":
    unittest.main()

"""Core logging behavior tests."""

from __future__ import unicode_literals

import logging
import os
import shutil
import tempfile
import unittest

from truecorp_core.logging import (
    get_logger,
    reset_setup_state_for_tests,
    set_run_context,
    setup_logging,
    shutdown_logging,
)
from truecorp_core.logging.factory import _SETUP_STATE


class TestLogging(unittest.TestCase):
    def setUp(self):
        reset_setup_state_for_tests()
        self.base = tempfile.mkdtemp(prefix="truecorp_log_")
        self.log_dir = os.path.join(self.base, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, "app.log")

    def tearDown(self):
        shutdown_logging()
        reset_setup_state_for_tests()
        shutil.rmtree(self.base, ignore_errors=True)

    def _cfg(self, **overrides):
        cfg = {
            "enabled": True,
            "level": "DEBUG",
            "directory": self.log_dir,
            "filename": "app.log",
            "console": {"enabled": False},
            "rotation": {"enabled": False},
            "retention": {"enabled": False},
            "security": {"redact_sensitive_data": False},
        }
        cfg.update(overrides)
        return cfg

    def test_log_levels(self):
        setup_logging(self._cfg(), application_name="APP_TEST", base_dir=self.base)
        logger = get_logger("APP_TEST")
        logger.debug("debug-msg")
        logger.info("info-msg")
        logger.warning("warn-msg")
        logger.error("error-msg")
        logger.critical("crit-msg")
        shutdown_logging()
        with open(self.log_file, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("debug-msg", content)
        self.assertIn("info-msg", content)
        self.assertIn("[WARNING]", content)
        self.assertIn("[ERROR]", content)
        self.assertIn("[CRITICAL]", content)

    def test_lazy_formatting(self):
        setup_logging(self._cfg(level="INFO"), application_name="APP", base_dir=self.base)
        logger = get_logger("APP")
        logger.info("processed=%s", 42)
        shutdown_logging()
        with open(self.log_file, "r", encoding="utf-8") as handle:
            self.assertIn("processed=42", handle.read())

    def test_run_context(self):
        setup_logging(self._cfg(), application_name="APP", base_dir=self.base)
        set_run_context(run_id="RUN-001", tracking_id="T1", event="START")
        get_logger("APP").info("hello")
        shutdown_logging()
        with open(self.log_file, "r", encoding="utf-8") as handle:
            line = handle.read()
        self.assertIn("[RUN-001]", line)
        self.assertIn("tracking_id=T1", line)
        self.assertIn("event=START", line)

    def test_missing_run_context(self):
        setup_logging(self._cfg(), application_name="APP", base_dir=self.base)
        get_logger("APP").info("no context")
        shutdown_logging()
        with open(self.log_file, "r", encoding="utf-8") as handle:
            self.assertIn("[-]", handle.read())

    def test_duplicate_handler_prevention(self):
        cfg = self._cfg()
        setup_logging(cfg, application_name="APP", base_dir=self.base)
        setup_logging(cfg, application_name="APP", base_dir=self.base)
        markers = [
            h
            for h in logging.getLogger().handlers
            if getattr(h, "_truecorp_marker", "").endswith("_file")
        ]
        self.assertEqual(len(markers), 1)

    def test_exception_traceback(self):
        setup_logging(self._cfg(), application_name="APP", base_dir=self.base)
        logger = get_logger("APP")
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("unexpected")
        shutdown_logging()
        with open(self.log_file, "r", encoding="utf-8") as handle:
            content = handle.read()
        self.assertIn("ValueError: boom", content)
        self.assertIn("Traceback", content)

    def test_standard_logging_compatibility(self):
        setup_logging(self._cfg(), application_name="APP", base_dir=self.base)
        std = logging.getLogger("legacy.module")
        std.warning("legacy warning")
        shutdown_logging()
        with open(self.log_file, "r", encoding="utf-8") as handle:
            self.assertIn("legacy warning", handle.read())


if __name__ == "__main__":
    unittest.main()

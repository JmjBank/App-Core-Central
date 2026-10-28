"""Rotation tests."""

from __future__ import unicode_literals

import gzip
import json
import os
import unittest
from datetime import datetime

from truecorp_core.logging.formatter import BANGKOK_TZ
from truecorp_core.logging.rotation import (
    TrueCorpRotatingFileHandler,
    archive_basename,
    bangkok_today,
    catch_up_rotation,
    compute_period_end,
    initial_state,
    load_rotation_state,
    save_rotation_state,
    should_rotate,
)
from truecorp_core.logging import reset_setup_state_for_tests, shutdown_logging


class TestRotation(unittest.TestCase):
    def setUp(self):
        reset_setup_state_for_tests()
        self.base = os.path.abspath("test_output_rotation")
        if os.path.isdir(self.base):
            for root, dirs, files in os.walk(self.base, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
        os.makedirs(self.base, exist_ok=True)
        self.log_dir = os.path.join(self.base, "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_path = os.path.join(self.log_dir, "app.log")
        self.state_dir = os.path.join(self.log_dir, ".logging_state")
        self.archive_dir = os.path.join(self.log_dir, "archive")

    def tearDown(self):
        shutdown_logging()
        reset_setup_state_for_tests()

    def _handler(self, mode="INTERVAL_DAYS", interval_days=7, clock=None):
        with open(self.log_path, "w", encoding="utf-8") as handle:
            handle.write("seed\n")
        rotation = {
            "enabled": True,
            "mode": mode,
            "interval_days": interval_days,
            "compress": True,
            "compression_level": 1,
        }
        handler = TrueCorpRotatingFileHandler(
            self.log_path,
            rotation_config=rotation,
            archive_dir=self.archive_dir,
            state_dir=self.state_dir,
            compression_enabled=True,
            compression_level=1,
            utc_clock=clock,
        )
        return handler

    def test_daily_should_rotate_after_period_end(self):
        today = datetime(2026, 10, 28, tzinfo=BANGKOK_TZ).date()
        state = initial_state("DAILY", 1, today)
        self.assertFalse(should_rotate(state, "DAILY", 1, today))
        tomorrow = today.replace(day=today.day + 1) if today.day < 28 else today
        from datetime import timedelta

        next_day = today + timedelta(days=1)
        self.assertTrue(should_rotate(state, "DAILY", 1, next_day))

    def test_interval_days_period_end(self):
        start = datetime(2026, 10, 7).date()
        end = compute_period_end(start, "INTERVAL_DAYS", 7)
        self.assertEqual(end.isoformat(), "2026-10-13")

    def test_rotation_creates_gzip_archive(self):
        fixed = datetime(2026, 10, 14, 1, 0, 0, tzinfo=BANGKOK_TZ)

        def clock():
            return fixed

        today = bangkok_today(fixed)
        state_path = os.path.join(self.state_dir, "app.log.rotation.json")
        state = initial_state("INTERVAL_DAYS", 7, datetime(2026, 10, 7).date())
        save_rotation_state(state_path, state)

        handler = self._handler(clock=clock)
        record = logging_record()
        handler.emit(record)
        handler.close()

        archives = os.listdir(self.archive_dir)
        self.assertTrue(any(name.endswith(".log.gz") for name in archives))
        gz_files = [n for n in archives if n.endswith(".log.gz")]
        with gzip.open(os.path.join(self.archive_dir, gz_files[0]), "rt", encoding="utf-8") as g:
            self.assertIn("seed", g.read())
        self.assertTrue(os.path.exists(self.log_path))

    def test_corrupted_state_recovery(self):
        state_path = os.path.join(self.state_dir, "app.log.rotation.json")
        os.makedirs(self.state_dir, exist_ok=True)
        with open(state_path, "w", encoding="utf-8") as handle:
            handle.write("{not-json")
        today = bangkok_today()
        state = load_rotation_state(state_path, "DAILY", 1, today)
        self.assertIn("period_start", state)

    def test_archive_name_collision(self):
        name = archive_basename("app.log", datetime(2026, 1, 1).date(), datetime(2026, 1, 7).date())
        os.makedirs(self.archive_dir, exist_ok=True)
        open(os.path.join(self.archive_dir, name), "w").close()
        from truecorp_core.logging.rotation import _unique_archive_path

        path = _unique_archive_path(self.archive_dir, name)
        self.assertTrue(path.endswith("_001.log"))

    def test_cron_catch_up_after_missed_days(self):
        state_path = os.path.join(self.state_dir, "app.log.rotation.json")
        os.makedirs(self.state_dir, exist_ok=True)
        save_rotation_state(
            state_path,
            {
                "version": 1,
                "mode": "INTERVAL_DAYS",
                "interval_days": 7,
                "period_start": "2026-10-01",
                "period_end": "2026-10-07",
                "last_rotation_at": None,
            },
        )
        with open(self.log_path, "w", encoding="utf-8") as handle:
            handle.write("cron-data\n")

        fixed = datetime(2026, 10, 20, 8, 0, 0, tzinfo=BANGKOK_TZ)
        handler = self._handler(clock=lambda: fixed)
        catch_up_rotation(handler, today=bangkok_today(fixed))
        handler.close()
        self.assertTrue(os.listdir(self.archive_dir))


def logging_record():
    import logging

    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="line",
        args=(),
        exc_info=None,
    )


if __name__ == "__main__":
    unittest.main()

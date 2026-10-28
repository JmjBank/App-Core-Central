"""Retention policy tests."""

from __future__ import unicode_literals

import os
import unittest
from datetime import datetime, timedelta

from truecorp_core.logging.formatter import BANGKOK_TZ
from truecorp_core.logging.retention import run_retention


class TestRetention(unittest.TestCase):
    def setUp(self):
        self.base = os.path.abspath("test_output_retention")
        self.archive = os.path.join(self.base, "archive")
        os.makedirs(self.archive, exist_ok=True)
        self.active = os.path.join(self.base, "app.log")
        with open(self.active, "w") as handle:
            handle.write("active")

    def _touch(self, name):
        path = os.path.join(self.archive, name)
        with open(path, "w") as handle:
            handle.write("x")
        return path

    def test_delete_expired_archive(self):
        old_end = (datetime.now(BANGKOK_TZ).date() - timedelta(days=120)).isoformat()
        old_start = (datetime.now(BANGKOK_TZ).date() - timedelta(days=126)).isoformat()
        path = self._touch("app.%s_%s.log.gz" % (old_start, old_end))
        result = run_retention(
            self.archive,
            self.active,
            retention_days=90,
            log_basename_prefix="app",
        )
        self.assertEqual(result.deleted, 1)
        self.assertFalse(os.path.exists(path))

    def test_keep_non_expired(self):
        end = datetime.now(BANGKOK_TZ).date().isoformat()
        start = end
        path = self._touch("app.%s_%s.log.gz" % (start, end))
        result = run_retention(
            self.archive,
            self.active,
            retention_days=90,
            log_basename_prefix="app",
        )
        self.assertEqual(result.deleted, 0)
        self.assertTrue(os.path.exists(path))

    def test_protect_active_log(self):
        path = os.path.join(self.archive, "app.log")
        with open(path, "w") as handle:
            handle.write("active copy")
        result = run_retention(
            self.archive,
            path,
            retention_days=0,
            log_basename_prefix="app",
        )
        self.assertTrue(os.path.exists(path))

    def test_protect_other_application_files(self):
        other = self._touch("other_app.2020-01-01_2020-01-07.log.gz")
        result = run_retention(
            self.archive,
            self.active,
            retention_days=0,
            log_basename_prefix="app",
        )
        self.assertEqual(result.deleted, 0)
        self.assertTrue(os.path.exists(other))

    def test_symlink_protection(self):
        end = datetime.now(BANGKOK_TZ).date().isoformat()
        start = end
        target = self._touch("app.%s_%s.log.gz" % (start, end))
        link = os.path.join(self.archive, "app.link.log.gz")
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            self.skipTest("symlink not supported")
        result = run_retention(
            self.archive,
            self.active,
            retention_days=90,
            log_basename_prefix="app",
        )
        self.assertEqual(result.deleted, 0)
        self.assertTrue(os.path.exists(target))


if __name__ == "__main__":
    unittest.main()

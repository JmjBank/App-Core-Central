import os
import unittest
from datetime import date
from unittest import mock

from truecorp_core.logging.retention import cleanup
from tests.support import TempTestCase, read_bytes

TODAY = date(2026, 10, 28)


class RetentionTests(TempTestCase):
    def setUp(self):
        TempTestCase.setUp(self)
        self.logs = self.path("logs")
        self.arch = os.path.join(self.logs, "archive")
        os.makedirs(self.arch)

    def touch(self, name, where=None, data=b"x"):
        path = os.path.join(where or self.arch, name)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def left(self):
        return sorted(os.listdir(self.arch))

    def test_expired_deleted_and_non_expired_kept_with_exact_boundary(self):
        self.touch("app.2026-01-01_2026-01-07.log.gz")  # 294 days old: expired
        self.touch("app.2026-07-01_2026-07-30.log.gz")  # exactly 90 days: kept (expires when > days)
        self.touch("app.2026-07-01_2026-07-29.log.gz")  # 91 days: expired
        self.touch("app.2026-10-14_2026-10-20.log.gz")  # recent
        res = cleanup(self.arch, "app", 90, TODAY)
        self.assertEqual(self.left(), ["app.2026-07-01_2026-07-30.log.gz", "app.2026-10-14_2026-10-20.log.gz"])
        self.assertEqual({k: res[k] for k in ("scanned", "expired", "deleted", "failed", "skipped")},
                         {"scanned": 4, "expired": 2, "deleted": 2, "failed": 0, "skipped": 0})

    def test_collision_suffix_names_and_plain_archives_expire_too(self):
        self.touch("app.2026-01-01_2026-01-07.1.log.gz")
        self.touch("app.2026-01-01_2026-01-07.log")
        cleanup(self.arch, "app", 90, TODAY)
        self.assertEqual(self.left(), [])

    def test_active_log_and_state_are_never_touched(self):
        active = self.touch("app.log", self.logs)
        state_dir = os.path.join(self.logs, ".logging_state")
        os.makedirs(state_dir)
        state = self.touch("app.rotation.json", state_dir)
        self.touch("app.2020-01-01_2020-01-07.log.gz")
        cleanup(self.arch, "app", 1, TODAY)
        self.assertTrue(os.path.exists(active))
        self.assertTrue(os.path.exists(state))

    def test_other_applications_and_unrelated_files_are_protected(self):
        self.touch("other.2020-01-01_2020-01-07.log.gz")
        self.touch("app2.2020-01-01_2020-01-07.log.gz")  # stem "app2" is not "app"
        self.touch("app.notes.txt")
        self.touch("app.2020-01-01_2020-01-07.log.gz.bak")
        self.touch("README")
        cleanup(self.arch, "app", 1, TODAY)
        self.assertEqual(len(self.left()), 5)

    def test_symlinked_file_is_never_followed_or_deleted(self):
        outside = self.touch("secret.txt", self.tmp, b"keep me")
        os.symlink(outside, os.path.join(self.arch, "app.2020-01-01_2020-01-07.log.gz"))
        res = cleanup(self.arch, "app", 1, TODAY)
        self.assertEqual(read_bytes(outside), b"keep me")
        self.assertEqual(res["skipped"], 1)
        self.assertEqual(res["deleted"], 0)

    def test_archive_directory_that_points_outside_is_refused(self):
        outside = self.path("elsewhere")
        os.makedirs(outside)
        victim = self.touch("app.2020-01-01_2020-01-07.log.gz", outside)
        os.rmdir(self.arch)
        os.symlink(outside, self.arch)
        res = cleanup(self.arch, "app", 1, TODAY)
        self.assertTrue(os.path.exists(victim))
        self.assertTrue(res["errors"])

    def test_permission_denied_counts_failure_and_continues(self):
        self.touch("app.2020-01-01_2020-01-07.log.gz")
        self.touch("app.2020-02-01_2020-02-07.log.gz")
        real = os.unlink

        def unlink(path, *a, **k):
            if "2020-01-01" in path:
                raise PermissionError(13, "denied")
            return real(path, *a, **k)

        with mock.patch("truecorp_core.logging.retention.os.unlink", side_effect=unlink):
            res = cleanup(self.arch, "app", 1, TODAY)
        self.assertEqual((res["deleted"], res["failed"]), (1, 1))
        self.assertEqual(self.left(), ["app.2020-01-01_2020-01-07.log.gz"])
        self.assertTrue(res["errors"])

    def test_archive_still_being_recovered_is_not_deleted(self):
        self.touch("app.2020-01-01_2020-01-07.log.gz")
        self.touch("app.2020-01-01_2020-01-07.log")  # original still present: recovery pending
        self.touch("app.2020-02-01_2020-02-07.log")
        self.touch("app.2020-02-01_2020-02-07.log.gz.tmp")  # compression in progress
        res = cleanup(self.arch, "app", 1, TODAY)
        self.assertEqual(len(self.left()), 4)
        self.assertEqual(res["deleted"], 0)
        self.assertEqual(res["skipped"], 3)

    def test_impossible_date_in_name_is_skipped(self):
        self.touch("app.2020-13-45_2020-99-99.log.gz")
        res = cleanup(self.arch, "app", 1, TODAY)
        self.assertEqual((res["deleted"], res["skipped"]), (0, 1))

    def test_works_when_nothing_is_logging(self):
        """Retention must not need any new log event (cron that has not run for months)."""
        self.touch("app.2020-01-01_2020-01-07.log.gz")
        self.assertEqual(cleanup(self.arch, "app", 90, TODAY)["deleted"], 1)


if __name__ == "__main__":
    unittest.main()

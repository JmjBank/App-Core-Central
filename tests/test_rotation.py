import json
import os
import unittest
from datetime import date
from unittest import mock

from truecorp_core.logging import rotation
from tests.support import FakeClock, TempTestCase, read_bytes, read_gz, read_json, read_text, write_json

INTERVAL7 = {"mode": "INTERVAL_DAYS", "interval_days": 7, "anchor_date": "2026-10-07"}


class CalendarMathTests(unittest.TestCase):
    def test_aligned_start_and_boundary(self):
        anchor = date(2026, 10, 7)
        self.assertEqual(rotation.aligned_start(anchor, 7, date(2026, 10, 13)), date(2026, 10, 7))
        self.assertEqual(rotation.aligned_start(anchor, 7, date(2026, 10, 14)), date(2026, 10, 14))
        self.assertEqual(rotation.aligned_start(anchor, 7, date(2026, 10, 29)), date(2026, 10, 28))
        self.assertEqual(rotation.next_boundary(anchor, 7, date(2026, 10, 7)), date(2026, 10, 14))

    def test_month_and_year_boundaries(self):
        self.assertEqual(rotation.next_boundary(date(2026, 12, 28), 7, date(2026, 12, 28)), date(2027, 1, 4))
        self.assertEqual(rotation.next_boundary(date(2028, 2, 26), 7, date(2028, 2, 26)), date(2028, 3, 4))  # leap year
        self.assertEqual(rotation.next_boundary(date(2026, 12, 31), 1, date(2026, 12, 31)), date(2027, 1, 1))


class RotationTests(TempTestCase):
    def test_daily_rotates_when_the_date_changes(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock)
        log.info("day one")
        clock.advance(seconds=3600)  # same Bangkok date: no rotation
        log.info("still day one")
        self.assertEqual(self.archives(cfg), [])
        clock.advance(days=1)
        log.info("day two")
        self.assertEqual(self.archives(cfg), ["app.2026-10-07_2026-10-07.log.gz"])
        self.assertIn("day one", read_gz(os.path.join(cfg.archive_dir, "app.2026-10-07_2026-10-07.log.gz")))
        active = read_text(cfg.log_path)
        self.assertIn("day two", active)
        self.assertNotIn("day one", active)

    def test_rotation_happens_at_bangkok_midnight_not_utc(self):
        clock = FakeClock(hour=23)  # 23:00 Bangkok = 16:00 UTC
        log, handler, cfg = self.make(clock)
        log.info("before midnight")
        clock.advance(seconds=3599)  # 23:59:59
        log.info("still same day")
        self.assertEqual(self.archives(cfg), [])
        clock.advance(seconds=2)  # 00:00:01 next day
        log.info("after midnight")
        self.assertEqual(len(self.archives(cfg)), 1)

    def test_interval_days_names_and_timing(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock, INTERVAL7)
        log.info("first")
        clock.advance(days=6)
        log.info("day 6")
        self.assertEqual(self.archives(cfg), [])
        clock.advance(days=1)
        log.info("day 7")
        self.assertEqual(self.archives(cfg), ["app.2026-10-07_2026-10-13.log.gz"])
        clock.advance(days=7)
        log.info("day 14")
        self.assertEqual(self.archives(cfg), ["app.2026-10-07_2026-10-13.log.gz",
                                              "app.2026-10-14_2026-10-20.log.gz"])

    def test_cron_restart_does_not_reset_the_cycle(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock, INTERVAL7)
        log.info("run 1")
        handler.close()
        state_path = cfg.state_path
        for _ in range(3):  # each cron start is a brand new handler
            clock.advance(days=2)
            log, handler, cfg = self.make(clock, INTERVAL7)
            log.info("cron run")
            handler.close()
        self.assertEqual(read_json(state_path)["period_start"], "2026-10-07")  # not reset by restarts
        self.assertEqual(self.archives(cfg), [])
        clock.advance(days=2)  # day 8: the first period is over
        log, handler, cfg = self.make(clock, INTERVAL7)
        log.info("after boundary")
        self.assertEqual(self.archives(cfg), ["app.2026-10-07_2026-10-13.log.gz"])
        self.assertEqual(read_json(state_path)["period_start"], "2026-10-14")

    def test_cron_down_for_many_days_recovers_on_next_start(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock, INTERVAL7)
        log.info("last run before outage")
        handler.close()
        clock.advance(days=22)  # 2026-10-29: three boundaries were missed
        log, handler, cfg = self.make(clock, INTERVAL7)
        log.info("back")
        self.assertEqual(self.archives(cfg), ["app.2026-10-07_2026-10-13.log.gz"])  # one archive, no empty ones
        self.assertEqual(read_json(cfg.state_path)["period_start"], "2026-10-28")
        self.assertIn("last run before outage",
                      read_gz(os.path.join(cfg.archive_dir, "app.2026-10-07_2026-10-13.log.gz")))
        self.assertEqual(read_text(cfg.log_path).count("back"), 1)

    def test_daemon_long_running_single_process(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock)
        total = 0
        for day in range(15):
            log.info("event day %d", day)
            total += 1
            clock.advance(days=1)
        self.assertEqual(len(self.archives(cfg)), 14)
        text = read_text(cfg.log_path) + "".join(
            read_gz(os.path.join(cfg.archive_dir, n)) for n in self.archives(cfg))
        self.assertEqual(text.count("event day"), total)  # nothing lost across 14 rotations

    def test_month_and_year_boundary_archive_names(self):
        clock = FakeClock(2026, 12, 28)
        log, handler, cfg = self.make(clock, {"mode": "INTERVAL_DAYS", "interval_days": 7,
                                              "anchor_date": "2026-12-28"})
        log.info("x")
        clock.advance(days=7)
        log.info("y")
        self.assertEqual(self.archives(cfg), ["app.2026-12-28_2027-01-03.log.gz"])

    def test_missing_state_starts_a_new_cycle_and_keeps_the_log(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock, INTERVAL7)
        log.info("precious")
        handler.close()
        os.unlink(cfg.state_path)
        log, handler, cfg = self.make(clock, INTERVAL7)
        self.assertTrue(os.path.exists(cfg.state_path))
        self.assertIn("precious", read_text(cfg.log_path))
        self.assertEqual(self.archives(cfg), [])

    def test_corrupted_state_is_quarantined_and_rebuilt(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock, INTERVAL7)
        log.info("precious")
        handler.close()
        for garbage in ("{not json", json.dumps({"schema": 1, "anchor": "2026-10-07",
                                                 "period_start": "2026-10-07", "crc": 1}), "[]", ""):
            with open(cfg.state_path, "w") as fh:
                fh.write(garbage)
            log, handler, cfg = self.make(clock, INTERVAL7)
            handler.close()
            self.assertIsNotNone(rotation.load_state(cfg.state_path)[1], garbage)  # valid again
        corrupt = [n for n in os.listdir(os.path.dirname(cfg.state_path)) if ".corrupt-" in n]
        self.assertGreaterEqual(len(corrupt), 1)  # evidence is kept, not deleted
        self.assertIn("precious", read_text(cfg.log_path))

    def test_state_file_roundtrip_is_checksummed(self):
        path = self.path("s.json")
        rotation.save_state(path, date(2026, 10, 7), date(2026, 10, 14))
        self.assertEqual(rotation.load_state(path), (date(2026, 10, 7), date(2026, 10, 14), "ok"))
        doc = read_json(path)
        doc["period_start"] = "2030-01-01"  # tampered without fixing crc
        write_json(path, doc)
        self.assertEqual(rotation.load_state(path)[2], "corrupt")

    def test_archive_name_collision_never_overwrites(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock, INTERVAL7)
        log.info("new data")
        existing = os.path.join(cfg.archive_dir, "app.2026-10-07_2026-10-13.log.gz")
        with open(existing, "wb") as fh:
            fh.write(b"OLD ARCHIVE")
        clock.advance(days=7)
        log.info("trigger")
        self.assertEqual(self.archives(cfg), ["app.2026-10-07_2026-10-13.1.log.gz",
                                              "app.2026-10-07_2026-10-13.log.gz"])
        self.assertEqual(read_bytes(existing), b"OLD ARCHIVE")
        self.assertIn("new data", read_gz(os.path.join(cfg.archive_dir, "app.2026-10-07_2026-10-13.1.log.gz")))

    def test_rotation_failure_keeps_active_log_and_retries(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock)
        log.info("must survive")
        clock.advance(days=1)
        with mock.patch("truecorp_core.logging.rotation.os.rename", side_effect=OSError(13, "denied")):
            with mock.patch("sys.stderr"):
                log.info("during failure")  # must not raise
        self.assertEqual(self.archives(cfg), [])
        text = read_text(cfg.log_path)
        self.assertIn("must survive", text)
        self.assertIn("during failure", text)
        self.assertIn("log maintenance failed", text)  # reported in the log itself
        clock.advance(seconds=120)  # past the retry back-off
        log.info("after recovery")
        self.assertEqual(len(self.archives(cfg)), 1)
        self.assertIn("must survive", read_gz(os.path.join(cfg.archive_dir, self.archives(cfg)[0])))

    def test_compress_disabled_keeps_plain_archive(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock, {"compress": False})
        log.info("x")
        clock.advance(days=1)
        log.info("y")
        self.assertEqual(self.archives(cfg), ["app.2026-10-07_2026-10-07.log"])

    def test_rotation_disabled_never_rotates(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock, {"enabled": False})
        log.info("a")
        clock.advance(days=30)
        log.info("b")
        self.assertEqual(self.archives(cfg), [])
        self.assertFalse(os.path.exists(cfg.state_path))

    def test_gzip_failure_during_rotation_keeps_uncompressed_archive_then_recovers(self):
        clock = FakeClock()
        log, handler, cfg = self.make(clock)
        log.info("data")
        clock.advance(days=1)
        with mock.patch("truecorp_core.logging.compression.gzip.open", side_effect=PermissionError(13, "denied")):
            with mock.patch("sys.stderr"):
                log.info("rotate with broken gzip")
        self.assertEqual(self.archives(cfg), ["app.2026-10-07_2026-10-07.log"])  # data still there, uncompressed
        handler.close()
        self.make(clock)  # next start repairs it
        self.assertEqual(self.archives(cfg), ["app.2026-10-07_2026-10-07.log.gz"])

    def test_second_handler_reopens_after_another_process_rotated(self):
        clock = FakeClock()
        log_a, handler_a, cfg = self.make(clock)
        log_b, handler_b, _ = self.make(clock)
        log_a.info("from a")
        log_b.info("from b")  # b keeps an fd on the same file
        clock.advance(days=1)
        log_a.info("a after rotation")  # a rotates the file under b's feet
        log_b.info("b after rotation")  # b must notice and reopen the new active file
        active = read_text(cfg.log_path)
        self.assertIn("a after rotation", active)
        self.assertIn("b after rotation", active)
        self.assertEqual(len(self.archives(cfg)), 1)


if __name__ == "__main__":
    unittest.main()

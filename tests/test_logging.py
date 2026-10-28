import logging
import os
import threading
import unittest
from datetime import datetime, timezone

from truecorp_core.logging import (ConfigError, LoggingSetupError, clear_run_context, get_logger, get_run_context,
                                   run_context, set_run_context, setup_logging, shutdown_logging)
from truecorp_core.logging.config import TZ
from truecorp_core.logging.formatter import TextFormatter
from tests.support import TempTestCase, read_text

LINE = r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[%s\] \[APP_X\] \[%s\] %s$"


class LoggingTests(TempTestCase):
    def setup(self, **extra):
        cfg = dict({"directory": "logs", "filename": "app.log", "level": "INFO"}, **extra)
        setup_logging(cfg, base_dir=self.tmp)
        return get_logger("APP_X")

    def lines(self):
        shutdown_logging()
        return read_text(self.path("logs", "app.log")).splitlines()

    def test_all_levels_and_default_plain_text_format(self):
        set_run_context("RUN-001")
        log = self.setup(level="DEBUG")
        log.debug("d")
        log.info("Application started")
        log.warning("w")
        log.error("e")
        log.critical("c")
        lines = self.lines()
        lines = [l for l in lines if "TRUECORP_LOGGING" not in l]  # ignore housekeeping notices
        self.assertEqual(len(lines), 5)
        for level, line in zip(("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), lines):
            self.assertRegex(line, LINE % (level, "RUN-001", ".*"))
        self.assertRegex(lines[1], LINE % ("INFO", "RUN-001", "Application started"))

    def test_level_filtering(self):
        log = self.setup(level="WARNING")
        log.info("hidden")
        log.warning("shown")
        self.assertEqual(len(self.lines()), 1)

    def test_lazy_formatting_and_standard_api(self):
        log = self.setup(level="DEBUG")
        log.info("processed=%s of %d", "x", 3)
        log.log(logging.INFO, "via log()")
        log.getChild("sub").info("child")
        self.assertTrue(log.isEnabledFor(logging.DEBUG))
        out = "\n".join(self.lines())
        self.assertIn("processed=x of 3", out)
        self.assertIn("via log()", out)
        self.assertIn("[APP_X.sub]", out)

    def test_bad_format_args_do_not_raise_into_the_application(self):
        log = self.setup()
        logging.raiseExceptions = False  # the stdlib prints the error to stderr when True; either way no raise
        self.addCleanup(setattr, logging, "raiseExceptions", True)
        log.info("needs two %s %s", "only-one")
        log.info("still alive")
        self.assertIn("still alive", "\n".join(self.lines()))

    def test_missing_context_renders_dash_and_does_not_fail(self):
        log = self.setup()
        log.info("no context")
        self.assertRegex(self.lines()[0], LINE % ("INFO", "-", "no context"))

    def test_context_fields_and_extra_fields(self):
        set_run_context("RUN-9", tracking_id="ABC123", batch_id="B1")
        log = self.setup()
        log.info("get", extra={"event": "IOM_GET_SUCCESS", "duration_ms": 1250, "step": "iom"})
        # known fields come first, in a fixed order, so lines stay grep-able
        self.assertRegex(self.lines()[0], LINE % (
            "INFO", "RUN-9", "get tracking_id=ABC123 batch_id=B1 event=IOM_GET_SUCCESS step=iom duration_ms=1250"))

    def test_timestamp_is_asia_bangkok(self):
        record = logging.LogRecord("truecorp.APP_X", logging.INFO, "p", 1, "m", (), None)
        record.created = datetime(2026, 10, 28, 8, 0, 1, tzinfo=timezone.utc).timestamp()
        self.assertTrue(TextFormatter().format(record).startswith("2026-10-28 15:00:01 "))
        self.assertEqual(TZ.utcoffset(None).total_seconds(), 7 * 3600)

    def test_exception_traceback_and_error_type(self):
        log = self.setup()
        try:
            {}["missing"]
        except KeyError:
            log.exception("Unexpected error")
        lines = self.lines()
        self.assertIn("error_type=KeyError", lines[0])
        self.assertTrue(any(l.startswith("    Traceback") for l in lines))

    def test_duplicate_handler_prevention_and_config_change_policy(self):
        pkg = logging.getLogger("truecorp")
        count = lambda: len([h for h in pkg.handlers if not isinstance(h, logging.NullHandler)])
        self.setup()
        self.setup()
        self.setup()
        self.assertEqual(count(), 1)
        log = self.setup(level="ERROR")  # changed config: replaced, not added
        self.assertEqual(count(), 1)
        log.warning("filtered by the new level")
        log.error("kept")
        self.assertEqual(len(self.lines()), 1)
        self.assertEqual(count(), 0)

    def test_console_handler_and_levels(self):
        self.setup(console={"enabled": True, "level": "ERROR"})
        kinds = sorted(type(h).__name__ for h in logging.getLogger("truecorp").handlers)
        self.assertEqual(kinds, ["NullHandler", "RotatingGzipHandler", "StreamHandler"])

    def test_does_not_touch_the_root_logger(self):
        before = list(logging.getLogger().handlers)
        root_level = logging.getLogger().level
        self.setup().info("x")
        self.assertEqual(logging.getLogger().handlers, before)
        self.assertEqual(logging.getLogger().level, root_level)
        self.assertFalse(logging.getLogger("truecorp").propagate)

    def test_disabled_logging_writes_nothing(self):
        setup_logging({"enabled": False, "directory": "logs"}, base_dir=self.tmp)
        get_logger("APP_X").error("nobody hears this")
        self.assertFalse(os.path.exists(self.path("logs")))

    def test_invalid_config_changes_nothing(self):
        self.setup()
        with self.assertRaises(ConfigError):
            setup_logging({"level": "LOUD"}, base_dir=self.tmp)
        self.assertEqual(len([h for h in logging.getLogger("truecorp").handlers
                              if not isinstance(h, logging.NullHandler)]), 1)

    def test_unwritable_directory_fails_fast_with_clear_error(self):
        blocker = self.path("blocker")
        open(blocker, "w").close()  # a file where the directory should be
        with self.assertRaises(LoggingSetupError):
            setup_logging({"directory": "blocker/logs"}, base_dir=self.tmp)

    def test_shutdown_is_idempotent_and_get_logger_validates(self):
        shutdown_logging()
        shutdown_logging()
        with self.assertRaises(ValueError):
            get_logger("")


class ContextTests(TempTestCase):
    def test_set_replaces_and_clear_clears(self):
        set_run_context("R1", tracking_id="A")
        set_run_context("R1", batch_id="B")
        self.assertEqual(get_run_context(), {"run_id": "R1", "batch_id": "B"})  # tracking_id did not leak
        clear_run_context()
        self.assertEqual(get_run_context(), {})

    def test_scoped_context_restores_outer(self):
        set_run_context("OUTER", batch_id="B")
        with run_context("INNER", tracking_id="T1"):
            self.assertEqual(get_run_context()["tracking_id"], "T1")
        self.assertEqual(get_run_context(), {"run_id": "OUTER", "batch_id": "B"})

    def test_threads_are_isolated(self):
        set_run_context("MAIN", tracking_id="M")
        seen = {}

        def worker():
            seen["start"] = get_run_context()
            set_run_context("W", tracking_id="WT")
            seen["end"] = get_run_context()

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertEqual(seen["start"], {})  # nothing inherited
        self.assertEqual(seen["end"]["tracking_id"], "WT")
        self.assertEqual(get_run_context()["tracking_id"], "M")  # nothing leaked back

    def test_validation(self):
        for args, kwargs in (((None,), {}), (("",), {}), (("R",), {"bad key": 1}), (("R",), {"a=b": 1})):
            with self.assertRaises(ValueError):
                set_run_context(*args, **kwargs)


if __name__ == "__main__":
    unittest.main()

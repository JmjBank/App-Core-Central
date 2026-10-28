"""Shared test helpers. Python 3.6 compatible, standard library only."""
import gzip
import json
import logging
import os
import shutil
import tempfile
import unittest
from datetime import datetime

from truecorp_core.logging import clear_run_context, shutdown_logging
from truecorp_core.logging.config import TZ, load_config
from truecorp_core.logging.formatter import TextFormatter
from truecorp_core.logging.rotation import RotatingGzipHandler


class FakeClock(object):
    """Controllable wall clock (Asia/Bangkok has no DST, so +86400s is always the next day)."""

    def __init__(self, year=2026, month=10, day=7, hour=12):
        self.now = datetime(year, month, day, hour, tzinfo=TZ).timestamp()

    def __call__(self):
        return self.now

    def advance(self, days=0, seconds=0):
        self.now += days * 86400 + seconds


def read_text(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


def read_json(path):
    with open(path, "r") as fh:
        return json.load(fh)


def write_json(path, doc):
    with open(path, "w") as fh:
        json.dump(doc, fh)


def read_gz(path):
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return fh.read()


class TempTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tcl_")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.addCleanup(clear_run_context)
        self.addCleanup(shutdown_logging)

    def path(self, *parts):
        return os.path.join(self.tmp, *parts)

    def make(self, clock, rotation=None, filename="app.log", **logging_cfg):
        """Build a handler + private logger directly (no global state). Returns (logger, handler, cfg)."""
        raw = {"directory": "logs", "filename": filename,
               "rotation": dict({"mode": "DAILY"}, **(rotation or {}))}
        raw.update(logging_cfg)
        cfg = load_config(raw, base_dir=self.tmp)
        handler = RotatingGzipHandler(cfg, clock=clock)
        handler.setFormatter(TextFormatter())
        handler.startup()
        self.addCleanup(handler.close)
        logger = logging.Logger("truecorp.T")
        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        return logger, handler, cfg

    def archives(self, cfg):
        return sorted(os.listdir(cfg.archive_dir))

"""Time-based log rotation with persistent state and cross-process locking."""

from __future__ import unicode_literals

import errno
import fcntl
import json
import logging
import os
import sys
from datetime import datetime, timedelta

from truecorp_core.logging.compression import (
    CompressionError,
    compress_file,
    recover_incomplete_compression,
)
from truecorp_core.logging.formatter import BANGKOK_TZ

STATE_VERSION = 1


class RotationStateError(Exception):
    pass


class FileLock(object):
    """Advisory flock lock with stale lock recovery (non-blocking retry)."""

    def __init__(self, lock_path):
        self.lock_path = lock_path
        self._handle = None

    def __enter__(self):
        lock_dir = os.path.dirname(self.lock_path)
        if lock_dir and not os.path.isdir(lock_dir):
            os.makedirs(lock_dir, exist_ok=True)
        self._handle = open(self.lock_path, "a")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
        except (IOError, OSError):
            self._handle.close()
            self._handle = None
            raise
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            except (IOError, OSError):
                pass
            self._handle.close()
            self._handle = None
        return False


def bangkok_today(now=None):
    if now is None:
        now = datetime.now(BANGKOK_TZ)
    return now.astimezone(BANGKOK_TZ).date()


def compute_period_end(period_start, mode, interval_days):
    if mode == "DAILY":
        return period_start
    return period_start + timedelta(days=int(interval_days) - 1)


def should_rotate(state, mode, interval_days, today):
    period_end = _parse_date(state.get("period_end"))
    if period_end is None:
        return True
    return today > period_end


def initial_state(mode, interval_days, today):
    period_start = today
    period_end = compute_period_end(period_start, mode, interval_days)
    return {
        "version": STATE_VERSION,
        "mode": mode,
        "interval_days": int(interval_days),
        "period_start": period_start.isoformat(),
        "period_end": period_end.isoformat(),
        "last_rotation_at": None,
    }


def load_rotation_state(state_path, mode, interval_days, today):
    if not os.path.exists(state_path):
        return initial_state(mode, interval_days, today)
    try:
        with open(state_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (IOError, OSError, ValueError):
        return initial_state(mode, interval_days, today)

    if not isinstance(data, dict):
        return initial_state(mode, interval_days, today)

    if data.get("mode") != mode:
        data = initial_state(mode, interval_days, today)
    if mode == "INTERVAL_DAYS" and int(data.get("interval_days", interval_days)) != int(
        interval_days
    ):
        data = initial_state(mode, interval_days, today)

    if not data.get("period_start") or not data.get("period_end"):
        return initial_state(mode, interval_days, today)
    return data


def save_rotation_state(state_path, state):
    state_dir = os.path.dirname(state_path)
    if state_dir and not os.path.isdir(state_dir):
        os.makedirs(state_dir, exist_ok=True)
    tmp_path = state_path + ".tmp"
    payload = json.dumps(state, sort_keys=True, indent=2, separators=(",", ": "))
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(tmp_path, state_path)
    except AttributeError:
        os.rename(tmp_path, state_path)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def archive_basename(log_filename, period_start, period_end):
    base, ext = os.path.splitext(log_filename)
    if not ext:
        ext = ".log"
    return "%s.%s_%s%s" % (
        base,
        period_start.isoformat(),
        period_end.isoformat(),
        ext,
    )


def _unique_archive_path(directory, filename):
    path = os.path.join(directory, filename)
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate_name = "%s_%03d%s" % (base, counter, ext)
        candidate = os.path.join(directory, candidate_name)
        if not os.path.exists(candidate):
            return candidate
        counter += 1


class TrueCorpRotatingFileHandler(logging.FileHandler):
    """File handler with Bangkok calendar rotation and optional gzip archives."""

    def __init__(
        self,
        filename,
        mode="a",
        encoding="utf-8",
        delay=False,
        rotation_config=None,
        archive_dir=None,
        state_dir=None,
        lock_path=None,
        compression_enabled=True,
        compression_level=6,
        utc_clock=None,
    ):
        self.rotation_config = rotation_config or {}
        self.rotation_enabled = bool(self.rotation_config.get("enabled", False))
        self.rotation_mode = self.rotation_config.get("mode", "DAILY")
        self.interval_days = int(self.rotation_config.get("interval_days", 7))
        self.compression_enabled = compression_enabled
        self.compression_level = int(compression_level)
        self.archive_dir = archive_dir
        self.state_path = None
        self.lock_path = lock_path
        self._utc_clock = utc_clock
        if self.rotation_enabled:
            log_dir = os.path.dirname(os.path.abspath(filename))
            base_name = os.path.basename(filename)
            if state_dir is None:
                state_dir = os.path.join(log_dir, ".logging_state")
            self.state_path = os.path.join(
                state_dir, base_name + ".rotation.json"
            )
            if lock_path is None:
                self.lock_path = os.path.join(
                    state_dir, base_name + ".rotation.lock"
                )
            if archive_dir is None:
                self.archive_dir = os.path.join(log_dir, "archive")
        super(TrueCorpRotatingFileHandler, self).__init__(
            filename, mode, encoding, delay
        )

    def _now(self):
        if self._utc_clock is not None:
            return self._utc_clock()
        return datetime.now(BANGKOK_TZ)

    def emit(self, record):
        if self.rotation_enabled:
            try:
                self._maybe_rotate()
            except Exception:
                self.handleError(record)
        super(TrueCorpRotatingFileHandler, self).emit(record)

    def _maybe_rotate(self):
        today = bangkok_today(self._now())
        with FileLock(self.lock_path):
            state = load_rotation_state(
                self.state_path,
                self.rotation_mode,
                self.interval_days,
                today,
            )
            if not should_rotate(state, self.rotation_mode, self.interval_days, today):
                return
            self._perform_rotation(state, today)

    def _perform_rotation(self, state, today):
        if not os.path.isdir(self.archive_dir):
            os.makedirs(self.archive_dir, exist_ok=True)

        period_start = _parse_date(state.get("period_start")) or today
        period_end = _parse_date(state.get("period_end")) or period_start

        if not os.path.exists(self.baseFilename):
            next_state = self._advance_state(state, today)
            save_rotation_state(self.state_path, next_state)
            return

        try:
            if os.path.getsize(self.baseFilename) == 0:
                next_state = self._advance_state(state, today)
                save_rotation_state(self.state_path, next_state)
                return
        except OSError:
            pass

        archive_name = archive_basename(
            os.path.basename(self.baseFilename), period_start, period_end
        )
        archive_path = _unique_archive_path(self.archive_dir, archive_name)

        self.acquire()
        try:
            if self.stream:
                self.stream.flush()
                self.stream.close()
                self.stream = None
            if os.path.exists(self.baseFilename):
                os.replace(self.baseFilename, archive_path)
        finally:
            self.release()

        if self.compression_enabled:
            gz_path = archive_path + ".gz"
            tmp_gz = gz_path + ".tmp"
            recover_incomplete_compression(tmp_gz, archive_path)
            try:
                compress_file(
                    archive_path,
                    gz_path,
                    compression_level=self.compression_level,
                )
            except CompressionError:
                sys.stderr.write(
                    "truecorp_core: gzip compression failed; "
                    "keeping uncompressed archive at %s\n" % archive_path
                )

        if not self.delay:
            self.stream = self._open()

        next_state = self._advance_state(state, today)
        next_state["last_rotation_at"] = self._now().isoformat()
        save_rotation_state(self.state_path, next_state)

    def _advance_state(self, state, today):
        new_start = today
        new_end = compute_period_end(
            new_start, self.rotation_mode, self.interval_days
        )
        return {
            "version": STATE_VERSION,
            "mode": self.rotation_mode,
            "interval_days": self.interval_days,
            "period_start": new_start.isoformat(),
            "period_end": new_end.isoformat(),
            "last_rotation_at": state.get("last_rotation_at"),
        }


def catch_up_rotation(handler, today=None):
    """Force rotation evaluation (for cron startup)."""
    if not handler.rotation_enabled:
        return
    if today is None:
        today = bangkok_today()
    with FileLock(handler.lock_path):
        state = load_rotation_state(
            handler.state_path,
            handler.rotation_mode,
            handler.interval_days,
            today,
        )
        while should_rotate(state, handler.rotation_mode, handler.interval_days, today):
            handler._perform_rotation(state, today)
            state = load_rotation_state(
                handler.state_path,
                handler.rotation_mode,
                handler.interval_days,
                today,
            )

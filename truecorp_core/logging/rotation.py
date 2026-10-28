"""Time-based rotation: DAILY and INTERVAL_DAYS, driven by a persisted state file.

Calendar model (Asia/Bangkok dates). Period boundaries are ``anchor + k * interval`` days
(DAILY = interval 1). The anchor is ``rotation.anchor_date`` if configured, otherwise the
date of the first run, stored in ``.logging_state/<stem>.rotation.json``. Restarting a cron
job therefore never resets the cycle, and a long outage simply lands in the period that
contains today (empty periods are skipped).

Rotation order (crash-safe at every step): rename active -> ``archive/<stem>.<start>_<end>.log``
(atomic, same filesystem) -> save state -> reopen the active file -> gzip (see compression.py).
A crash between steps is repaired at the next start (``compression.recover`` / state rebuild).

Concurrency: rotation/retention run only while holding a non-blocking flock; a process that
cannot get it skips this time and retries later (never waits). Every process checks the
inode of the path before each write and reopens if another process rotated the file.
"""
import json
import logging
import os
import sys
import time
import zlib
from datetime import datetime, timedelta

from . import compression, retention
from .config import NOTICE_NAME, TZ, LoggingSetupError, archive_basename
from .lock import FileLock

RETRY_SECONDS = 60
_DATE = "%Y-%m-%d"


# ---------------------------------------------------------------- calendar helpers
def _parse(text):
    return datetime.strptime(text, _DATE).date()


def today_bkk(epoch):
    return datetime.fromtimestamp(epoch, TZ).date()


def midnight_epoch(day):
    return datetime(day.year, day.month, day.day, tzinfo=TZ).timestamp()


def aligned_start(anchor, interval, day):
    """Start date of the period (anchor + k*interval) that contains ``day``."""
    return anchor + timedelta(days=((day - anchor).days // interval) * interval)


def next_boundary(anchor, interval, period_start):
    return aligned_start(anchor, interval, period_start) + timedelta(days=interval)


# ---------------------------------------------------------------- state file
def _crc(payload):
    return zlib.crc32(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")) & 0xFFFFFFFF


def save_state(path, anchor, period_start):
    """Atomic: write temp file, fsync, rename over the old state."""
    payload = {"schema": 1, "anchor": anchor.strftime(_DATE), "period_start": period_start.strftime(_DATE)}
    doc = dict(payload, crc=_crc(payload))
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w") as fh:
        json.dump(doc, fh, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def load_state(path):
    """Returns (anchor, period_start, status); status is 'ok', 'missing' or 'corrupt'.
    A corrupt file is moved aside (never deleted) so the cycle can be rebuilt."""
    try:
        with open(path, "r") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None, None, "missing"
    except ValueError:
        return None, None, _quarantine(path)
    try:
        crc = doc.pop("crc")
        if doc.get("schema") != 1 or crc != _crc(doc):
            raise ValueError("checksum mismatch")
        return _parse(doc["anchor"]), _parse(doc["period_start"]), "ok"
    except (KeyError, ValueError, TypeError, AttributeError):
        return None, None, _quarantine(path)


def _quarantine(path):
    try:
        os.replace(path, "%s.corrupt-%d" % (path, int(time.time())))
    except OSError:
        pass  # will be overwritten by the next save; the rebuild must not depend on it
    return "corrupt"


# ---------------------------------------------------------------- handler
class RotatingGzipHandler(logging.FileHandler):
    """File handler with calendar rotation, gzip and retention. ``clock`` is injectable for tests."""

    def __init__(self, cfg, clock=time.time):
        self.cfg = cfg
        self._clock = clock
        self._notices = []
        self._next_epoch = None
        self._flock = FileLock(cfg.lock_path)
        logging.FileHandler.__init__(self, cfg.log_path, mode="a", encoding="utf-8", delay=True)

    # -- diagnostics: never raised into the application; WARNING+ also goes to stderr
    def _note(self, level, message):
        self._notices.append((level, message))
        if level >= logging.WARNING:
            try:
                sys.stderr.write("[truecorp_core.logging] %s\n" % message)
            except (OSError, ValueError):
                pass  # closed/broken stderr (daemon); the notice is still written to the log file

    def _flush_notices(self):
        notices, self._notices = self._notices, []
        for level, message in notices:
            if level < self.level:  # housekeeping lines obey the configured level like everything else
                continue
            record = logging.LogRecord(NOTICE_NAME, level, __file__, 0, message, (), None)
            logging.FileHandler.emit(self, record)

    # -- lifecycle
    def startup(self):
        """Create directories, repair/rotate/clean up, then open the active log."""
        cfg = self.cfg
        try:
            for directory in (cfg.directory, cfg.archive_dir, cfg.state_dir):
                os.makedirs(directory, exist_ok=True)
            self._maintenance(startup=True)
            self.stream = self._open()
        except OSError as exc:
            raise LoggingSetupError("cannot prepare log directory %s: %s" % (cfg.directory, exc))
        self._flush_notices()

    def _close_stream(self):
        stream, self.stream = self.stream, None
        if stream is not None:
            try:
                stream.flush()
            finally:
                stream.close()

    def emit(self, record):
        try:
            self._rotate_if_needed()
            self._reopen_if_moved()
        except Exception as exc:  # noqa: housekeeping must never stop the record from being written
            self._note(logging.WARNING, "log housekeeping failed: %s" % exc)
        logging.FileHandler.emit(self, record)
        if self._notices:
            self._flush_notices()

    def _reopen_if_moved(self):
        """Another process may have rotated the file: our fd then points at the archive."""
        if self.stream is None:
            return
        try:
            now = os.stat(self.baseFilename)
            mine = os.fstat(self.stream.fileno())
            if (now.st_dev, now.st_ino) == (mine.st_dev, mine.st_ino):
                return
        except OSError:
            pass  # path missing or fd unusable: reopen
        self._close_stream()

    def _rotate_if_needed(self):
        if not self.cfg.rot_enabled:
            return
        now = self._clock()
        if self._next_epoch is not None and now < self._next_epoch:
            return
        self._maintenance()

    # -- the locked critical section
    def _maintenance(self, startup=False):
        cfg = self.cfg
        now = self._clock()
        try:
            got = self._flock.try_acquire()
        except OSError as exc:
            self._note(logging.WARNING, "cannot take rotation lock: %s" % exc)
            self._next_epoch = now + RETRY_SECONDS
            return
        if not got:  # another process is rotating; do not wait, ask again later
            self._next_epoch = now + RETRY_SECONDS
            return
        try:
            rotated = False
            if cfg.rot_enabled:
                for level, message in compression.recover(cfg.archive_dir, cfg.stem, cfg.compression_level,
                                                          cfg.compress):
                    self._note(level, message)
                rotated = self._rotate_if_due(now)
            if cfg.ret_enabled and (rotated or (startup and cfg.ret_cleanup_on_startup)):
                self._cleanup(now)
        except Exception as exc:  # noqa: any failure here must not reach the application; back off and report
            self._note(logging.WARNING, "log maintenance failed, will retry: %s" % exc)
            self._next_epoch = now + RETRY_SECONDS
        finally:
            self._flock.release()

    def _rotate_if_due(self, now):
        cfg = self.cfg
        today = today_bkk(now)
        anchor, start, status = load_state(cfg.state_path)
        if status == "corrupt":
            self._note(logging.WARNING, "rotation state was corrupt; moved aside and rebuilt")
        anchor = cfg.anchor_date or anchor or today
        interval = cfg.rot_interval

        if start is None:  # first run, or state lost: start a fresh cycle, keep the existing log as is
            start = aligned_start(anchor, interval, today)
            save_state(cfg.state_path, anchor, start)
            self._next_epoch = midnight_epoch(start + timedelta(days=interval))
            return False

        boundary = next_boundary(anchor, interval, start)
        if today < boundary:
            self._next_epoch = midnight_epoch(boundary)
            return False

        archived = self._archive(start, boundary - timedelta(days=1))
        new_start = aligned_start(anchor, interval, today)
        save_state(cfg.state_path, anchor, new_start)
        self._next_epoch = midnight_epoch(new_start + timedelta(days=interval))
        if archived and cfg.compress:
            try:
                compression.compress_file(archived, cfg.compression_level)
            except compression.CompressionError as exc:
                self._note(logging.WARNING, "kept %s uncompressed, will retry at next start/rotation: %s"
                           % (os.path.basename(archived), exc))
        return True

    def _archive(self, start, end):
        """Move the active log to a collision-free archive name. Returns its path or None."""
        cfg = self.cfg
        self._close_stream()
        try:
            if os.path.getsize(cfg.log_path) == 0:
                return None
        except FileNotFoundError:
            return None  # nothing to archive (e.g. an earlier attempt already moved it)
        number = 0
        while True:
            target = os.path.join(cfg.archive_dir, archive_basename(cfg.stem, start, end, number))
            if not any(os.path.lexists(p) for p in (target, target + ".gz", target + ".gz.tmp")):
                break
            number += 1
        os.makedirs(cfg.archive_dir, exist_ok=True)
        os.rename(cfg.log_path, target)  # failure leaves the active log untouched
        self._note(logging.INFO, "rotated %s -> archive/%s" % (cfg.filename, os.path.basename(target)))
        return target

    def _cleanup(self, now):
        cfg = self.cfg
        res = retention.cleanup(cfg.archive_dir, cfg.stem, cfg.ret_days, today_bkk(now))
        # A cron job that starts every minute must not add a line per start when nothing happened.
        busy = res["expired"] or res["failed"] or res["errors"]
        self._note(logging.INFO if busy else logging.DEBUG,
                   "retention cleanup scanned=%d expired=%d deleted=%d failed=%d skipped=%d"
                   % (res["scanned"], res["expired"], res["deleted"], res["failed"], res["skipped"]))
        for error in res["errors"]:
            self._note(logging.WARNING, "retention: %s" % error)
        return res

    def run_cleanup(self):
        """Manual retention cleanup. Returns the result dict, or None if another process holds the lock."""
        if not self._flock.try_acquire():
            return None
        try:
            result = self._cleanup(self._clock())
        finally:
            self._flock.release()
        with self.lock:
            self._flush_notices()
        return result

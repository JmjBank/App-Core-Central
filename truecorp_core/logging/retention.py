"""Retention cleanup for archived log files."""

from __future__ import unicode_literals

import os
import re
from datetime import datetime, timedelta

from truecorp_core.logging.formatter import BANGKOK_TZ

ARCHIVE_DATE_PATTERN = re.compile(
    r"\.(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.log(\.gz)?$"
)


class RetentionResult(object):
    def __init__(self):
        self.found = 0
        self.deleted = 0
        self.failed = 0
        self.skipped = 0
        self.errors = []

    def to_dict(self):
        return {
            "found": self.found,
            "deleted": self.deleted,
            "failed": self.failed,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


def _parse_archive_end_date(filename):
    match = ARCHIVE_DATE_PATTERN.search(filename)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("end"), "%Y-%m-%d").date()
    except ValueError:
        return None


def _is_safe_archive_path(path, archive_dir):
    archive_real = os.path.realpath(archive_dir)
    path_real = os.path.realpath(path)
    if not path_real.startswith(archive_real + os.sep) and path_real != archive_real:
        return False
    if os.path.islink(path):
        return False
    return True


def run_retention(
    archive_dir,
    active_log_path,
    retention_days,
    log_basename_prefix,
    now=None,
):
    """
    Delete archived logs older than retention_days (by archive period end date).
    Never deletes active_log_path or files not matching this application's prefix.
    """
    result = RetentionResult()
    if not os.path.isdir(archive_dir):
        return result

    if now is None:
        now = datetime.now(BANGKOK_TZ)
    cutoff = now.date() - timedelta(days=int(retention_days))

    active_real = os.path.realpath(active_log_path) if active_log_path else None

    for name in os.listdir(archive_dir):
        if not name.startswith(log_basename_prefix):
            result.skipped += 1
            continue
        full_path = os.path.join(archive_dir, name)
        if not _is_safe_archive_path(full_path, archive_dir):
            result.skipped += 1
            continue
        if active_real and os.path.realpath(full_path) == active_real:
            result.skipped += 1
            continue
        if name.endswith(".tmp"):
            result.skipped += 1
            continue

        result.found += 1
        end_date = _parse_archive_end_date(name)
        if end_date is None:
            result.skipped += 1
            continue
        if end_date >= cutoff:
            continue

        try:
            os.remove(full_path)
            result.deleted += 1
        except OSError as exc:
            result.failed += 1
            result.errors.append("%s: %s" % (full_path, exc))

    return result

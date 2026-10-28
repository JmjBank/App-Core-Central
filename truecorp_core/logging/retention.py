"""Delete expired archived logs, and nothing else.

Age rule: an archive is expired when ``today - <end date in its file name> > days``
(the end date is the archive metadata; file mtimes are not trusted). Only files that
match ``<stem>.<start>_<end>[.<n>].log[.gz]`` in the archive directory are candidates,
so the active log, other applications' files and unrelated files are never touched.
"""
import os
import stat
from datetime import datetime

from .config import ARCHIVE_DIR_NAME, archive_regex


def cleanup(archive_dir, stem, days, today):
    """Returns a dict: scanned, expired, deleted, failed, skipped, errors (list of text)."""
    result = {"scanned": 0, "expired": 0, "deleted": 0, "failed": 0, "skipped": 0, "errors": []}
    parent = os.path.realpath(os.path.dirname(archive_dir))
    if os.path.realpath(archive_dir) != os.path.join(parent, ARCHIVE_DIR_NAME):
        # archive directory is a symlink pointing elsewhere: refuse rather than delete outside it
        result["errors"].append("archive directory %s resolves outside the log directory; cleanup refused"
                                % archive_dir)
        return result
    pattern = archive_regex(stem)
    try:
        names = sorted(os.listdir(archive_dir))
    except OSError as exc:
        result["errors"].append("cannot list %s: %s" % (archive_dir, exc))
        return result
    present = set(names)

    for name in names:
        match = pattern.match(name)
        if not match:
            continue
        result["scanned"] += 1
        path = os.path.join(archive_dir, name)
        try:
            end = datetime.strptime(match.group(2), "%Y-%m-%d").date()
            if (today - end).days <= days:
                continue
            result["expired"] += 1
            if not stat.S_ISREG(os.lstat(path).st_mode):  # symlink / directory: never followed, never deleted
                result["skipped"] += 1
                continue
            base = name[:-3] if name.endswith(".gz") else name
            if (name.endswith(".gz") and base in present) or (name.endswith(".log") and name + ".gz" in present) \
                    or (base + ".gz.tmp") in present:
                result["skipped"] += 1  # original and archive coexist: compression recovery owns this pair
                continue
            os.unlink(path)
            result["deleted"] += 1
        except ValueError:
            result["skipped"] += 1  # name matched the pattern but is not a real date
        except OSError as exc:  # permission denied etc.: count it, keep going
            result["failed"] += 1
            result["errors"].append("%s: %s" % (name, exc))
    return result

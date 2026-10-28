"""Safe gzip of archived logs (never the active log).

Sequence: write ``<archive>.log.gz.tmp`` -> read it back and compare size+CRC32 with the
source -> re-check the source did not grow -> atomically ``os.replace`` into place ->
only then delete the original. Any failure (permission denied, disk full, corrupt
output) leaves the original untouched and removes the temp file. ``recover()`` finishes
work interrupted by a kill/crash at any of those points.
"""
import gzip
import logging
import os
import stat
import time
import zlib

from .config import archive_regex

CHUNK = 1024 * 1024
_MASK = 0xFFFFFFFF


class CompressionError(Exception):
    """Compression or verification failed; the original file is still intact."""


def _drain(fileobj):
    size, crc = 0, 0
    while True:
        chunk = fileobj.read(CHUNK)
        if not chunk:
            return size, crc & _MASK
        size += len(chunk)
        crc = zlib.crc32(chunk, crc)


def file_stats(path):
    """(size, crc32) of a plain file."""
    with open(path, "rb") as fh:
        return _drain(fh)


def gzip_stats(path):
    """(size, crc32) of the UNCOMPRESSED content of a gzip file; CompressionError if it is corrupt."""
    try:
        with gzip.open(path, "rb") as fh:
            return _drain(fh)
    except (OSError, EOFError, zlib.error) as exc:
        raise CompressionError("corrupt or unreadable gzip %s: %s" % (path, exc))


def _unlink_quiet(path):
    try:
        os.unlink(path)
    except OSError:
        pass


def compress_file(src, level=6, retries=3):
    """Compress ``src`` to ``src + '.gz'`` and delete ``src``. Returns the .gz path."""
    dst = src + ".gz"
    tmp = dst + ".tmp"
    if os.path.lexists(dst):
        raise CompressionError("refusing to overwrite existing archive %s" % dst)
    try:
        for _ in range(retries):
            size, crc = 0, 0
            with open(src, "rb") as fin, gzip.open(tmp, "wb", compresslevel=level) as fout:
                while True:
                    chunk = fin.read(CHUNK)
                    if not chunk:
                        break
                    fout.write(chunk)
                    size += len(chunk)
                    crc = zlib.crc32(chunk, crc)
            if gzip_stats(tmp) != (size, crc & _MASK):
                raise CompressionError("integrity check failed for %s" % tmp)
            if os.stat(src).st_size != size:
                continue  # a late writer appended while we were compressing: redo with the new content
            if os.path.lexists(dst):
                raise CompressionError("refusing to overwrite existing archive %s" % dst)
            os.replace(tmp, dst)
            os.unlink(src)
            return dst
        raise CompressionError("%s kept changing during compression; left uncompressed" % src)
    except CompressionError:
        _unlink_quiet(tmp)
        raise
    except OSError as exc:  # permission denied, disk full (ENOSPC), vanished file ...
        _unlink_quiet(tmp)
        raise CompressionError("cannot compress %s: %s" % (src, exc))


def recover(archive_dir, stem, level=6, compress=True):
    """Finish interrupted compressions for one stem. Returns [(levelno, message)] to report."""
    notes = []
    pattern = archive_regex(stem)
    try:
        names = sorted(os.listdir(archive_dir))
    except OSError as exc:
        return [(logging.WARNING, "cannot list archive directory %s: %s" % (archive_dir, exc))]

    def is_regular(path):
        return stat.S_ISREG(os.lstat(path).st_mode)  # never follow or touch symlinks

    for name in names:  # incomplete temp files are by definition unusable: the original is still there
        path = os.path.join(archive_dir, name)
        if name.endswith(".gz.tmp") and pattern.match(name[:-len(".gz.tmp")]):
            try:
                if is_regular(path):
                    os.unlink(path)
                    notes.append((logging.WARNING, "removed incomplete compression file %s" % name))
            except OSError as exc:
                notes.append((logging.WARNING, "cannot remove %s: %s" % (name, exc)))

    for name in names:
        path = os.path.join(archive_dir, name)
        if not (name.endswith(".log") and pattern.match(name)):
            continue
        gz = path + ".gz"
        try:
            if not is_regular(path):
                continue
            if os.path.lexists(gz):
                if is_regular(gz) and gzip_stats_safe(gz) == file_stats(path):
                    os.unlink(path)  # compression had finished; only the delete was missing
                    notes.append((logging.INFO, "removed already-compressed original %s" % name))
                    continue
                bad = "%s.corrupt-%d" % (gz, int(time.time()))
                os.replace(gz, bad)  # keep the evidence, never delete an unverified archive
                notes.append((logging.WARNING, "bad archive %s.gz moved to %s" % (name, os.path.basename(bad))))
            if compress:
                compress_file(path, level)
                notes.append((logging.INFO, "recovered pending compression of %s" % name))
        except (OSError, CompressionError) as exc:
            notes.append((logging.WARNING, "recovery of %s failed, original kept: %s" % (name, exc)))
    return notes


def gzip_stats_safe(path):
    try:
        return gzip_stats(path)
    except CompressionError:
        return None

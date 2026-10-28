"""Gzip compression for archived log files."""

from __future__ import unicode_literals

import gzip
import os
import shutil


class CompressionError(Exception):
    pass


def _unique_destination(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    counter = 1
    while True:
        candidate = "%s_%03d%s" % (base, counter, ext)
        if not os.path.exists(candidate):
            return candidate
        counter += 1


def compress_file(source_path, dest_path, compression_level=6):
    """
    Compress source_path to dest_path using a temporary file and atomic rename.
    Original file is removed only after integrity verification.
    """
    if not os.path.isfile(source_path):
        raise CompressionError("Source file does not exist: %s" % source_path)

    if os.path.exists(dest_path):
        dest_path = _unique_destination(dest_path)

    dest_dir = os.path.dirname(dest_path) or "."
    tmp_path = dest_path + ".tmp"
    if os.path.exists(tmp_path):
        try:
            os.remove(tmp_path)
        except OSError:
            pass

    try:
        with open(source_path, "rb") as src:
            with gzip.open(tmp_path, "wb", compresslevel=compression_level) as dst:
                shutil.copyfileobj(src, dst)
    except (IOError, OSError) as exc:
        _safe_remove(tmp_path)
        raise CompressionError("Compression failed: %s" % exc)

    if not _verify_gzip(tmp_path):
        _safe_remove(tmp_path)
        raise CompressionError("Compressed file failed integrity check")

    try:
        os.replace(tmp_path, dest_path)
    except AttributeError:
        if os.path.exists(dest_path):
            raise CompressionError("Archive already exists: %s" % dest_path)
        os.rename(tmp_path, dest_path)

    try:
        os.remove(source_path)
    except OSError as exc:
        raise CompressionError(
            "Archive created but failed to remove source: %s" % exc
        )

    return dest_path


def recover_incomplete_compression(tmp_path, source_path=None):
    """Remove stale temp gzip if source still exists."""
    if not os.path.exists(tmp_path):
        return False
    if source_path and os.path.exists(source_path):
        _safe_remove(tmp_path)
        return True
    if not _verify_gzip(tmp_path):
        _safe_remove(tmp_path)
        return True
    return False


def _verify_gzip(path):
    try:
        with gzip.open(path, "rb") as handle:
            while handle.read(65536):
                pass
        return True
    except (IOError, OSError):
        return False


def _safe_remove(path):
    try:
        os.remove(path)
    except OSError:
        pass

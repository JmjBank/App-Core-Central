import errno
import gzip
import os
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from truecorp_core.logging import compression
from truecorp_core.logging.compression import CompressionError, compress_file, recover
from tests.support import TempTestCase, read_bytes, read_gz

NAME = "app.2026-10-07_2026-10-13.log"


class CompressionTests(TempTestCase):
    def archive(self, content=b"line 1\nline 2\n"):
        os.makedirs(self.path("archive"), exist_ok=True)
        path = self.path("archive", NAME)
        with open(path, "wb") as fh:
            fh.write(content)
        return path

    def test_successful_gzip_removes_original_after_verification(self):
        src = self.archive(b"hello\n" * 1000)
        dst = compress_file(src, level=9)
        self.assertEqual(dst, src + ".gz")
        self.assertFalse(os.path.exists(src))
        self.assertFalse(os.path.exists(dst + ".tmp"))
        self.assertEqual(read_gz(dst), "hello\n" * 1000)

    def test_compression_level_is_honoured(self):
        data = os.urandom(10) * 5000
        sizes = []
        for level in (1, 9):
            src = self.archive(data)
            sizes.append(os.path.getsize(compress_file(src, level)))
            os.unlink(src + ".gz")
        self.assertLessEqual(sizes[1], sizes[0])

    def test_corrupted_gzip_is_detected(self):
        bad = self.path("bad.gz")
        with gzip.open(bad, "wb") as fh:
            fh.write(b"x" * 10000)
        blob = bytearray(read_bytes(bad))
        blob[len(blob) // 2] ^= 0xFF
        with open(bad, "wb") as fh:
            fh.write(bytes(blob))
        with self.assertRaises(CompressionError):
            compression.gzip_stats(bad)
        with open(bad, "wb") as fh:
            fh.write(b"not gzip at all")
        with self.assertRaises(CompressionError):
            compression.gzip_stats(bad)

    def test_failed_integrity_check_keeps_original(self):
        src = self.archive()
        with mock.patch("truecorp_core.logging.compression.gzip_stats", return_value=(0, 0)):
            with self.assertRaises(CompressionError):
                compress_file(src)
        self.assertEqual(read_bytes(src), b"line 1\nline 2\n")
        self.assertFalse(os.path.exists(src + ".gz"))
        self.assertFalse(os.path.exists(src + ".gz.tmp"))

    def test_permission_denied_keeps_original_and_cleans_temp(self):
        src = self.archive()
        with mock.patch("truecorp_core.logging.compression.gzip.open", side_effect=PermissionError(13, "denied")):
            with self.assertRaises(CompressionError):
                compress_file(src)
        self.assertEqual(read_bytes(src), b"line 1\nline 2\n")
        self.assertFalse(os.path.exists(src + ".gz.tmp"))

    def test_disk_full_while_writing_keeps_original_and_cleans_temp(self):
        src = self.archive()

        class FullDisk(object):
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def write(self, data):
                raise OSError(errno.ENOSPC, "No space left on device")

        real_open = gzip.open
        # create the real .tmp file first so we can prove it is removed
        def fake_open(path, mode="rb", *a, **k):
            if mode == "wb":
                open(path, "wb").close()
                return FullDisk()
            return real_open(path, mode, *a, **k)

        with mock.patch("truecorp_core.logging.compression.gzip.open", side_effect=fake_open):
            with self.assertRaises(CompressionError) as ctx:
                compress_file(src)
        self.assertIn("No space left", str(ctx.exception))
        self.assertEqual(read_bytes(src), b"line 1\nline 2\n")
        self.assertFalse(os.path.exists(src + ".gz.tmp"))

    def test_refuses_to_overwrite_existing_archive(self):
        src = self.archive()
        with open(src + ".gz", "wb") as fh:
            fh.write(b"PRECIOUS")
        with self.assertRaises(CompressionError):
            compress_file(src)
        self.assertEqual(read_bytes(src + ".gz"), b"PRECIOUS")
        self.assertTrue(os.path.exists(src))

    def test_source_that_grows_during_compression_is_recompressed(self):
        src = self.archive(b"first\n")
        real_stat = os.stat
        calls = {"n": 0}

        def stat(path, *a, **k):
            if path == src and calls["n"] == 0:  # first check: a late writer has appended meanwhile
                calls["n"] += 1
                with open(src, "ab") as fh:
                    fh.write(b"late\n")
            return real_stat(path, *a, **k)

        with mock.patch("truecorp_core.logging.compression.os.stat", side_effect=stat):
            dst = compress_file(src)
        self.assertEqual(read_gz(dst), "first\nlate\n")  # the late line is in the archive, not lost

    def test_source_that_never_stops_changing_is_left_alone(self):
        src = self.archive(b"x\n")
        real_stat = os.stat
        fake = SimpleNamespace(st_size=10 ** 9)

        def stat(path, *a, **k):
            return fake if path == src else real_stat(path, *a, **k)

        with mock.patch("truecorp_core.logging.compression.os.stat", side_effect=stat):
            with self.assertRaises(CompressionError):
                compress_file(src, retries=2)
        self.assertTrue(os.path.exists(src))
        self.assertFalse(os.path.exists(src + ".gz"))


class RecoveryTests(TempTestCase):
    def setUp(self):
        TempTestCase.setUp(self)
        self.dir = self.path("archive")
        os.makedirs(self.dir)
        self.log = os.path.join(self.dir, NAME)

    def write(self, path, data):
        with open(path, "wb") as fh:
            fh.write(data)

    def test_killed_during_compression_leaves_tmp_and_original(self):
        self.write(self.log, b"data\n")
        self.write(self.log + ".gz.tmp", b"\x1f\x8b partial")  # process was killed here
        notes = recover(self.dir, "app")
        self.assertEqual(read_gz(self.log + ".gz"), "data\n")
        self.assertEqual(sorted(os.listdir(self.dir)), [NAME + ".gz"])
        self.assertTrue(notes)

    def test_killed_after_replace_before_delete_removes_verified_original(self):
        self.write(self.log, b"data\n")
        compress_file_copy = self.log + ".gz"
        with gzip.open(compress_file_copy, "wb") as fh:
            fh.write(b"data\n")
        recover(self.dir, "app")
        self.assertEqual(sorted(os.listdir(self.dir)), [NAME + ".gz"])

    def test_bad_archive_next_to_original_is_quarantined_not_deleted(self):
        self.write(self.log, b"data\n")
        self.write(self.log + ".gz", b"corrupt")
        recover(self.dir, "app")
        names = sorted(os.listdir(self.dir))
        self.assertEqual(names[0], NAME + ".gz")
        self.assertTrue(names[1].startswith(NAME + ".gz.corrupt-"))  # evidence kept
        self.assertEqual(read_gz(self.log + ".gz"), "data\n")

    def test_orphan_original_is_compressed_and_other_stems_are_ignored(self):
        other = os.path.join(self.dir, "other.2026-10-07_2026-10-13.log")
        self.write(self.log, b"mine\n")
        self.write(other, b"not mine\n")
        recover(self.dir, "app")
        self.assertTrue(os.path.exists(self.log + ".gz"))
        self.assertEqual(read_bytes(other), b"not mine\n")  # untouched

    def test_compress_false_does_not_touch_plain_archives(self):
        self.write(self.log, b"mine\n")
        recover(self.dir, "app", compress=False)
        self.assertEqual(os.listdir(self.dir), [NAME])

    def test_permission_failure_in_recovery_keeps_original(self):
        self.write(self.log, b"mine\n")
        with mock.patch("truecorp_core.logging.compression.gzip.open", side_effect=PermissionError(13, "denied")):
            notes = recover(self.dir, "app")
        self.assertTrue(os.path.exists(self.log))
        self.assertTrue(any("failed" in message for _, message in notes))

    def test_symlinks_are_never_followed(self):
        outside = self.path("outside.log")
        self.write(outside, b"outside\n")
        os.symlink(outside, self.log)
        recover(self.dir, "app")
        self.assertEqual(read_bytes(outside), b"outside\n")
        self.assertTrue(os.path.islink(self.log))


if __name__ == "__main__":
    unittest.main()

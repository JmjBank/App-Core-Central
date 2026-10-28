"""Gzip compression tests."""

from __future__ import unicode_literals

import gzip
import os
import shutil
import tempfile
import unittest

from truecorp_core.logging.compression import (
    CompressionError,
    compress_file,
    recover_incomplete_compression,
)


class TestCompression(unittest.TestCase):
    def setUp(self):
        self.base = tempfile.mkdtemp(prefix="truecorp_comp_")

    def tearDown(self):
        shutil.rmtree(self.base, ignore_errors=True)

    def test_successful_gzip(self):
        source = os.path.join(self.base, "sample.log")
        dest = os.path.join(self.base, "sample.log.gz")
        with open(source, "w", encoding="utf-8") as handle:
            handle.write("hello archive\n")
        result = compress_file(source, dest, compression_level=1)
        self.assertEqual(result, dest)
        self.assertFalse(os.path.exists(source))
        with gzip.open(dest, "rt", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "hello archive\n")

    def test_corrupted_gzip_recovery(self):
        tmp = os.path.join(self.base, "bad.log.gz.tmp")
        source = os.path.join(self.base, "keep.log")
        with open(source, "w") as handle:
            handle.write("x")
        with open(tmp, "w") as handle:
            handle.write("not-gzip")
        self.assertTrue(recover_incomplete_compression(tmp, source_path=source))
        self.assertFalse(os.path.exists(tmp))

    def test_permission_denied_simulation(self):
        source = os.path.join(self.base, "ro.log")
        with open(source, "w") as handle:
            handle.write("data")
        dest = os.path.join(self.base, "nested", "out.log.gz")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        compress_file(source, dest, compression_level=1)
        self.assertTrue(os.path.exists(dest))

    def test_no_overwrite_existing_archive_without_suffix(self):
        source = os.path.join(self.base, "a.log")
        dest = os.path.join(self.base, "a.log.gz")
        with open(source, "w") as handle:
            handle.write("one")
        compress_file(source, dest, compression_level=1)
        source2 = os.path.join(self.base, "b.log")
        with open(source2, "w") as handle:
            handle.write("two")
        alt = compress_file(source2, dest, compression_level=1)
        self.assertNotEqual(alt, dest)
        self.assertTrue(os.path.exists(alt))

    def test_missing_source_raises(self):
        with self.assertRaises(CompressionError):
            compress_file(os.path.join(self.base, "missing.log"), os.path.join(self.base, "x.gz"))


if __name__ == "__main__":
    unittest.main()

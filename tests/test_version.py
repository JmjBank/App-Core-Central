"""Version synchronization tests."""

from __future__ import unicode_literals

import os
import unittest

import truecorp_core


class TestVersion(unittest.TestCase):
    def test_version_format(self):
        parts = truecorp_core.__version__.split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            self.assertTrue(part.isdigit())

    def test_version_matches_files(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "VERSION"), encoding="utf-8") as handle:
            root_version = handle.read().strip()
        with open(
            os.path.join(root, "truecorp_core", "VERSION"), encoding="utf-8"
        ) as handle:
            pkg_version = handle.read().strip()
        self.assertEqual(truecorp_core.__version__, root_version)
        self.assertEqual(root_version, pkg_version)


if __name__ == "__main__":
    unittest.main()

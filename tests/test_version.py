import ast
import importlib
import os
import sys
import tempfile
import unittest

import truecorp_core
from truecorp_core import version
from tests.support import read_text

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "tools"))
import check_version  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_semver_format_and_package_attribute(self):
        self.assertRegex(truecorp_core.__version__, r"^\d+\.\d+\.\d+$")
        self.assertEqual(truecorp_core.__version__, version.read_version())

    def test_development_version_is_0_1_0(self):
        self.assertEqual(truecorp_core.__version__, "0.1.0")

    def test_version_is_identical_in_source_metadata_and_docs(self):
        self.assertEqual(check_version.check(), [])

    def test_version_never_changes_by_importing_or_running(self):
        before = read_text(os.path.join(REPO, "VERSION"))
        importlib.reload(version)
        self.assertEqual(read_text(os.path.join(REPO, "VERSION")), before)

    def test_invalid_version_file_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix="VERSION", delete=False) as fh:
            fh.write("1.0")
        self.addCleanup(os.unlink, fh.name)
        with self.assertRaises(ValueError):
            version.read_version(fh.name)


class Python36SyntaxTests(unittest.TestCase):
    """Static evidence only: the real Python 3.6 runtime is verified separately (see COMPATIBILITY.md)."""

    @unittest.skipIf(sys.version_info < (3, 8), "ast feature_version needs Python 3.8+")
    def test_all_sources_parse_as_python_3_6(self):
        checked = 0
        for folder in ("truecorp_core", "tests", "examples", "tools"):
            for root, _, files in os.walk(os.path.join(REPO, folder)):
                for name in files:
                    if name.endswith(".py"):
                        path = os.path.join(root, name)
                        with open(path, "r", encoding="utf-8") as fh:
                            ast.parse(fh.read(), path, feature_version=(3, 6))
                        checked += 1
        self.assertGreater(checked, 20)

    def test_library_uses_only_standard_library(self):
        stdlib_ok = set(getattr(sys, "stdlib_module_names", ()))
        imported = set()
        for root, _, files in os.walk(os.path.join(REPO, "truecorp_core")):
            for name in files:
                if name.endswith(".py"):
                    with open(os.path.join(root, name), "r", encoding="utf-8") as fh:
                        for node in ast.walk(ast.parse(fh.read())):
                            if isinstance(node, ast.Import):
                                imported.update(a.name.split(".")[0] for a in node.names)
                            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                                imported.add(node.module.split(".")[0])
        imported.discard("truecorp_core")
        if stdlib_ok:
            self.assertEqual(imported - stdlib_ok, set())
        else:  # Python < 3.10: no stdlib list available, check against the known set we use
            self.assertLessEqual(imported, {"os", "re", "sys", "json", "gzip", "zlib", "time", "stat", "errno",
                                            "logging", "threading", "datetime", "contextlib", "fcntl"})


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python
"""Release check: the version must be identical everywhere (run before tagging a release).

    python tools/check_version.py            # exit 0 = consistent, 1 = mismatch

Checks: root VERSION, truecorp_core/VERSION (what truecorp_core.__version__ reads), the newest
CHANGELOG.md heading, and the "Version:" line in README.md and COMPATIBILITY.md.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def _read(*parts):
    with open(os.path.join(ROOT, *parts), "r", encoding="utf-8") as fh:
        return fh.read()


def check():
    """Returns a list of problems (empty list = consistent)."""
    problems = []
    root_version = _read("VERSION").strip()
    if not SEMVER.match(root_version):
        problems.append("VERSION %r is not MAJOR.MINOR.PATCH" % root_version)
    found = {"truecorp_core/VERSION": _read("truecorp_core", "VERSION").strip()}
    match = re.search(r"^## \[(\d+\.\d+\.\d+)\]", _read("CHANGELOG.md"), re.M)
    found["CHANGELOG.md (newest heading)"] = match.group(1) if match else None
    for doc in ("README.md", "COMPATIBILITY.md"):
        match = re.search(r"^\**Version:?\**:?\s*`?(\d+\.\d+\.\d+)`?", _read(doc), re.M | re.I)
        found[doc + " (Version: line)"] = match.group(1) if match else None
    for where, value in sorted(found.items()):
        if value != root_version:
            problems.append("%s says %s but VERSION is %s" % (where, value, root_version))
    return problems


if __name__ == "__main__":
    issues = check()
    for issue in issues:
        print("MISMATCH: " + issue)
    print("version check: %s" % ("FAILED" if issues else "OK (%s)" % _read("VERSION").strip()))
    sys.exit(1 if issues else 0)

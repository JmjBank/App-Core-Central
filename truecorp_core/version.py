"""Single source of truth for the library version.

The version lives in the ``VERSION`` file that ships *inside* this package, so it
is copied together with the directory on FTP/SFTP deployments. The repository-root
``VERSION`` must match it; ``tools/check_version.py`` (run by the unit tests and by
the release procedure) enforces that, plus CHANGELOG/README/COMPATIBILITY.
Nothing ever bumps the version at runtime.
"""
import os
import re

_VERSION_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "VERSION")
_SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def read_version(path=_VERSION_FILE):
    with open(path, "r") as fh:
        value = fh.read().strip()
    if not _SEMVER.match(value):
        raise ValueError("invalid version %r in %s (expected MAJOR.MINOR.PATCH)" % (value, path))
    return value


__version__ = read_version()

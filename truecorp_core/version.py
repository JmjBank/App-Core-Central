"""Package version — primary source: repository ``VERSION``, portable copy: ``truecorp_core/VERSION``."""

import os

_PKG_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_PKG_DIR)


def _read_version():
    candidates = (
        os.path.join(_REPO_ROOT, "VERSION"),
        os.path.join(_PKG_DIR, "VERSION"),
    )
    for path in candidates:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                version = handle.read().strip()
        except (IOError, OSError):
            continue
        if version:
            return version
    return "0.0.0"


__version__ = _read_version()

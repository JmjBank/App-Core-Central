"""Shared test helpers."""

from __future__ import unicode_literals

import os
import shutil
import tempfile


class TempAppDir(object):
    def __init__(self):
        self.path = tempfile.mkdtemp(prefix="truecorp_test_")

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)


def write_config(base_dir, logging_section, filename="test.log"):
    log_dir = os.path.join(base_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    return {
        "enabled": True,
        "level": "DEBUG",
        "directory": log_dir,
        "filename": filename,
        "console": {"enabled": False, "level": "WARNING"},
        "rotation": {"enabled": False},
        "retention": {"enabled": False},
        **logging_section,
    }

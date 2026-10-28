#!/usr/bin/env python3
"""Example long-running daemon loop (simulated with short iterations)."""

from __future__ import print_function

import json
import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, ROOT)

from truecorp_core.logging import get_logger, set_run_context, setup_logging  # noqa: E402


def main():
    config_path = os.path.join(BASE_DIR, "config.json")
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    setup_logging(
        config["logging"],
        application_name=config["application"]["name"],
        base_dir=BASE_DIR,
    )
    logger = get_logger(config["application"]["name"])

    for idx in range(3):
        set_run_context(run_id="RUN-DAEMON-%03d" % idx, batch_id="BATCH-1")
        logger.info("daemon heartbeat iteration=%s", idx)
        time.sleep(1)
    return 0


if __name__ == "__main__":
    sys.exit(main())

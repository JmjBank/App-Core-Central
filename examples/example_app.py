#!/usr/bin/env python3
"""Example batch/cron-style application using TrueCorp logging."""

from __future__ import print_function

import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, ROOT)

from truecorp_core.logging import (  # noqa: E402
    clear_run_context,
    get_logger,
    set_run_context,
    setup_logging,
    shutdown_logging,
)


def main():
    config_path = os.path.join(BASE_DIR, "config.json")
    with open(config_path, "r", encoding="utf-8") as handle:
        config = json.load(handle)

    setup_logging(
        config["logging"],
        application_name=config["application"]["name"],
        environment=config["application"]["environment"],
        base_dir=BASE_DIR,
    )

    set_run_context(run_id="RUN-20261028-001", tracking_id="ABC123")
    logger = get_logger(config["application"]["name"])
    logger.info("Application started")
    logger.info("event=IOM_GET_START")
    logger.info("event=IOM_GET_SUCCESS duration_ms=%s", 1250)
    clear_run_context()
    shutdown_logging()
    return 0


if __name__ == "__main__":
    sys.exit(main())

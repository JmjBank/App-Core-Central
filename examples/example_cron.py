"""Cron-style job: starts, does its work, exits. Every start is a new process.

    PYTHONPATH=/path/to/APP/lib python3 example_cron.py [--base-dir DIR]

(Running straight from the repository also works: the repo root is added to sys.path.)
"""
import argparse
import json
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repository layout only; on a server use PYTHONPATH=lib

from truecorp_core.logging import (clear_run_context, get_logger, set_run_context,  # noqa: E402
                                   setup_logging, shutdown_logging)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(HERE, "config.json"))
    parser.add_argument("--base-dir", default=HERE, help="relative log paths resolve from here (not from the CWD)")
    args = parser.parse_args(argv)
    with open(args.config, "r") as fh:
        config = json.load(fh)

    setup_logging(config["logging"], base_dir=args.base_dir)
    logger = get_logger(config["application"]["name"])
    run_id = "RUN-%s-%s" % (time.strftime("%Y%m%d"), uuid.uuid4().hex[:6])
    set_run_context(run_id)
    started = time.time()
    logger.info("Application started")
    failed = 0
    try:
        for tracking_id in ("ABC123", "XYZ456"):
            set_run_context(run_id, tracking_id=tracking_id)  # replaces the previous tracking id
            logger.info("fetching order", extra={"event": "IOM_GET_START"})
            try:
                if tracking_id == "XYZ456":
                    raise TimeoutError("HTTP_TIMEOUT password=not-for-the-log")
                logger.info("order fetched", extra={"event": "IOM_GET_SUCCESS", "duration_ms": 1250})
            except TimeoutError:
                failed += 1
                logger.exception("order failed", extra={"event": "IOM_GET_FAILED"})
        set_run_context(run_id)
        logger.info("Application finished", extra={"duration_ms": int((time.time() - started) * 1000)})
    finally:
        clear_run_context()
        shutdown_logging()
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

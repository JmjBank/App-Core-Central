"""Long-running daemon: one process logs for days; rotation/retention happen inside it.

    PYTHONPATH=/path/to/APP/lib python3 example_app.py [--iterations N] [--interval SECONDS]

--iterations 0 (default) runs until SIGTERM/Ctrl-C. Worker threads must call set_run_context
themselves: context is per thread and is not inherited.
"""
import argparse
import json
import os
import signal
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))  # repository layout only; on a server use PYTHONPATH=lib

from truecorp_core.logging import (get_logger, run_context, set_run_context,  # noqa: E402
                                   setup_logging, shutdown_logging)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=os.path.join(HERE, "config.json"))
    parser.add_argument("--base-dir", default=HERE)
    parser.add_argument("--iterations", type=int, default=0)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args(argv)
    with open(args.config, "r") as fh:
        config = json.load(fh)

    setup_logging(config["logging"], base_dir=args.base_dir)
    logger = get_logger(config["application"]["name"])
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    set_run_context("DAEMON-%d" % os.getpid())
    logger.info("Daemon started")
    count = 0
    try:
        while not stop.is_set() and (args.iterations == 0 or count < args.iterations):
            count += 1
            with run_context("DAEMON-%d" % os.getpid(), batch_id="B%d" % count):  # scoped: no leakage
                logger.info("processing batch", extra={"step": "work"})
            stop.wait(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        logger.info("Daemon stopped after %d batches", count)
        shutdown_logging()
    return 0


if __name__ == "__main__":
    sys.exit(main())

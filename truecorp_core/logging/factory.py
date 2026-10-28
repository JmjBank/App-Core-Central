"""Public setup/teardown API.

All handlers are attached to the package logger ``truecorp`` (propagate=False), and
``get_logger("APP")`` returns ``truecorp.APP``. The application's root logger and any
existing handlers are never touched, so legacy logging keeps working unchanged.

setup_logging() policy:
* same configuration again  -> no-op (idempotent, no duplicate handlers)
* different configuration   -> the new handlers replace the old ones (last call wins);
                               the swap happens only after the new handlers started OK
* invalid configuration     -> ConfigError, nothing is changed
* unusable log directory    -> LoggingSetupError (fail fast at startup, never silently run without logs)
Runtime problems (rotation, gzip, retention, disk full while writing) never raise into the
application; they are reported on stderr and, where possible, as WARNING lines in the log.
"""
import logging
import sys
import threading

from .config import LoggingSetupError, load_config
from .formatter import PREFIX, TextFormatter
from .rotation import RotatingGzipHandler
from .security import Redactor

PACKAGE_LOGGER = PREFIX.rstrip(".")

_lock = threading.RLock()
_state = {"signature": None, "handlers": [], "file_handler": None}

# library etiquette: silent until setup_logging() is called
logging.getLogger(PACKAGE_LOGGER).addHandler(logging.NullHandler())


def get_logger(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError("logger name must be a non-empty string")
    return logging.getLogger(name if name.startswith(PREFIX) else PREFIX + name)


def _remove_handlers(handlers):
    package = logging.getLogger(PACKAGE_LOGGER)
    for handler in handlers:
        package.removeHandler(handler)
        try:
            handler.flush()
        finally:
            handler.close()


def setup_logging(config=None, base_dir=None):
    cfg = load_config(config, base_dir)  # validate everything before touching any state
    with _lock:
        if _state["signature"] == cfg.signature():
            return
        handlers, file_handler = [], None
        if cfg.enabled:
            formatter = TextFormatter(Redactor(cfg.redact_fields) if cfg.redact_enabled else None)
            try:
                file_handler = RotatingGzipHandler(cfg)
                file_handler.setLevel(cfg.level)
                file_handler.setFormatter(formatter)
                handlers.append(file_handler)
                file_handler.startup()
                if cfg.console_enabled:
                    console = logging.StreamHandler(sys.stderr)
                    console.setLevel(cfg.console_level)
                    console.setFormatter(formatter)
                    handlers.append(console)
            except LoggingSetupError:
                for handler in handlers:
                    handler.close()
                raise

        package = logging.getLogger(PACKAGE_LOGGER)
        package.propagate = False
        _remove_handlers(_state["handlers"])
        for handler in handlers:
            package.addHandler(handler)
        package.setLevel(min([h.level for h in handlers]) if handlers else logging.CRITICAL + 1)
        _state.update(signature=cfg.signature(), handlers=handlers, file_handler=file_handler)


def shutdown_logging():
    """Flush and close our handlers. Safe to call repeatedly or without setup."""
    with _lock:
        _remove_handlers(_state["handlers"])
        _state.update(signature=None, handlers=[], file_handler=None)


def cleanup_logs():
    """Run retention cleanup now. Returns the counts dict, or None if logging is not set up
    or another process currently holds the maintenance lock."""
    with _lock:
        handler = _state["file_handler"]
    return handler.run_cleanup() if handler is not None else None

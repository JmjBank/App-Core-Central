"""TrueCorp core logging (plain text, rotation, gzip, retention, redaction).

    from truecorp_core.logging import setup_logging, get_logger

NOTE: this package is named ``logging``. Inside it, ``import logging`` is still the
standard library (Python 3 absolute imports), but never run a script from inside this
directory, or the current directory would shadow the standard library.
"""
from .config import ConfigError, LoggingSetupError
from .context import clear_run_context, get_run_context, run_context, set_run_context
from .factory import cleanup_logs, get_logger, setup_logging, shutdown_logging

__all__ = [
    "setup_logging", "get_logger", "set_run_context", "clear_run_context", "shutdown_logging",
    "cleanup_logs", "run_context", "get_run_context", "ConfigError", "LoggingSetupError",
]

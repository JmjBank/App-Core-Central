"""Logging factory — setup, logger access, and lifecycle."""

from __future__ import unicode_literals

import json
import logging
import os
import sys
import warnings

from truecorp_core.logging.config import LoggingConfigError, normalize_logging_config
from truecorp_core.logging.context import ContextFilter, clear_run_context
from truecorp_core.logging.formatter import TrueCorpFormatter
from truecorp_core.logging.retention import run_retention
from truecorp_core.logging.rotation import TrueCorpRotatingFileHandler, catch_up_rotation

_SETUP_STATE = {
    "configured": False,
    "config_fingerprint": None,
    "application_name": None,
    "environment": None,
    "file_handler": None,
    "console_handler": None,
}

_HANDLER_MARKER = "truecorp_core_handler"
_FILTER_MARKER = "truecorp_core_context_filter"


class LoggingSetupError(RuntimeError):
    pass


def _config_fingerprint(normalized):
    payload = json.dumps(normalized, sort_keys=True, default=str)
    return payload


def setup_logging(
    config,
    application_name=None,
    environment=None,
    base_dir=None,
):
    """
    Configure application logging. Idempotent for identical configuration.

    If called again with a different configuration, existing handlers are kept
    and a RuntimeWarning is emitted (fail-safe for running applications).
    """
    try:
        normalized = normalize_logging_config(config, base_dir=base_dir)
    except LoggingConfigError as exc:
        raise LoggingSetupError(str(exc))

    fingerprint = _config_fingerprint(normalized)

    if _SETUP_STATE["configured"]:
        if _SETUP_STATE["config_fingerprint"] != fingerprint:
            warnings.warn(
                "setup_logging() called with different configuration after "
                "logging was already configured; keeping original handlers.",
                RuntimeWarning,
            )
        return normalized

    if not normalized.get("enabled", True):
        _SETUP_STATE["configured"] = True
        _SETUP_STATE["config_fingerprint"] = fingerprint
        return normalized

    app_name = application_name or normalized.get("application_name") or "APP"
    env = environment or normalized.get("environment") or ""

    log_dir = normalized["directory"]
    if not os.path.isdir(log_dir):
        os.makedirs(log_dir, exist_ok=True)

    log_path = os.path.join(log_dir, normalized["filename"])
    archive_dir = os.path.join(log_dir, "archive")
    state_dir = os.path.join(log_dir, ".logging_state")

    security = normalized.get("security") or {}
    rotation = normalized.get("rotation") or {}
    retention = normalized.get("retention") or {}

    formatter = TrueCorpFormatter(
        application_name=app_name,
        redact_sensitive_data=security.get("redact_sensitive_data", True),
        redact_fields=security.get("redact_fields"),
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, normalized["level"]))

    file_handler = TrueCorpRotatingFileHandler(
        log_path,
        encoding="utf-8",
        rotation_config=rotation,
        archive_dir=archive_dir,
        state_dir=state_dir,
        compression_enabled=bool(rotation.get("compress", True)),
        compression_level=int(rotation.get("compression_level", 6)),
    )
    file_handler._truecorp_marker = _HANDLER_MARKER + "_file"
    file_handler.setFormatter(formatter)
    file_handler.setLevel(getattr(logging, normalized["level"]))
    root.addHandler(file_handler)

    if rotation.get("enabled"):
        catch_up_rotation(file_handler)

    console_handler = None
    console_cfg = normalized.get("console") or {}
    if console_cfg.get("enabled"):
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler._truecorp_marker = _HANDLER_MARKER + "_console"
        console_handler.setFormatter(formatter)
        console_handler.setLevel(getattr(logging, console_cfg.get("level", "WARNING")))
        root.addHandler(console_handler)

    context_filter = ContextFilter()
    file_handler.addFilter(context_filter)
    if console_handler is not None:
        console_handler.addFilter(context_filter)

    if retention.get("enabled") and retention.get("cleanup_on_startup", True):
        prefix = os.path.splitext(normalized["filename"])[0]
        run_retention(
            archive_dir=archive_dir,
            active_log_path=log_path,
            retention_days=retention.get("days", 90),
            log_basename_prefix=prefix,
        )

    _SETUP_STATE["configured"] = True
    _SETUP_STATE["config_fingerprint"] = fingerprint
    _SETUP_STATE["application_name"] = app_name
    _SETUP_STATE["environment"] = env
    _SETUP_STATE["file_handler"] = file_handler
    _SETUP_STATE["console_handler"] = console_handler

    logging.getLogger(__name__).debug(
        "TrueCorp logging configured application=%s environment=%s log_path=%s",
        app_name,
        env,
        log_path,
    )
    return normalized


def get_logger(name):
    """Return a standard library logger (compatible with logging.getLogger)."""
    return logging.getLogger(name)


def set_run_context(run_id=None, **fields):
    from truecorp_core.logging.context import set_run_context as _set

    return _set(run_id=run_id, **fields)


def shutdown_logging():
    root = logging.getLogger()
    to_remove = []
    for handler in root.handlers[:]:
        marker = getattr(handler, "_truecorp_marker", "") or ""
        if marker.startswith(_HANDLER_MARKER):
            to_remove.append(handler)
    for handler in to_remove:
        handler.flush()
        handler.close()
        root.removeHandler(handler)

    root.setLevel(logging.WARNING)
    clear_run_context()
    _SETUP_STATE["configured"] = False
    _SETUP_STATE["config_fingerprint"] = None
    _SETUP_STATE["file_handler"] = None
    _SETUP_STATE["console_handler"] = None


def reset_setup_state_for_tests():
    """Internal helper for unit tests."""
    shutdown_logging()
    _SETUP_STATE["configured"] = False
    _SETUP_STATE["config_fingerprint"] = None

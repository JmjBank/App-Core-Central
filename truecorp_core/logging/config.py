"""Logging configuration validation and normalization."""

from __future__ import unicode_literals

import os

DEFAULT_LOGGING_CONFIG = {
    "enabled": True,
    "level": "INFO",
    "directory": "./logs",
    "filename": "application.log",
    "console": {
        "enabled": False,
        "level": "WARNING",
    },
    "rotation": {
        "enabled": False,
        "mode": "DAILY",
        "interval_days": 7,
        "compress": True,
        "compression_level": 6,
    },
    "retention": {
        "enabled": False,
        "days": 90,
        "cleanup_on_startup": True,
    },
    "security": {
        "redact_sensitive_data": True,
        "redact_fields": [],
    },
}

VALID_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
ROTATION_MODES = ("DAILY", "INTERVAL_DAYS")


class LoggingConfigError(ValueError):
    """Raised when logging configuration is invalid."""


def _deep_merge(base, override):
    result = dict(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _validate_level(level, path):
    if not isinstance(level, str):
        raise LoggingConfigError("%s must be a string log level" % path)
    upper = level.upper()
    if upper not in VALID_LEVELS:
        raise LoggingConfigError(
            "%s must be one of %s, got %r" % (path, VALID_LEVELS, level)
        )
    return upper


def _is_safe_path_component(name):
    if not name or name in (".", ".."):
        return False
    if os.path.isabs(name):
        return False
    if ".." in name.split(os.sep):
        return False
    return True


def resolve_path(path_value, base_dir, label):
    if path_value is None or path_value == "":
        raise LoggingConfigError("%s must not be empty" % label)
    if not isinstance(path_value, str):
        raise LoggingConfigError("%s must be a string path" % label)

    expanded = os.path.expanduser(path_value)
    if os.path.isabs(expanded):
        resolved = os.path.normpath(expanded)
    else:
        if base_dir is None:
            base_dir = os.getcwd()
        resolved = os.path.normpath(os.path.join(base_dir, expanded))

    base_real = os.path.realpath(base_dir if base_dir else os.getcwd())
    resolved_real = os.path.realpath(resolved)

    if not resolved_real.startswith(base_real):
        if os.path.isabs(expanded):
            pass
        else:
            raise LoggingConfigError(
                "%s resolves outside application base directory: %s"
                % (label, resolved)
            )
    return resolved


def normalize_logging_config(config, base_dir=None):
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise LoggingConfigError("logging config must be a dict")

    merged = _deep_merge(DEFAULT_LOGGING_CONFIG, config)

    merged["level"] = _validate_level(merged.get("level", "INFO"), "logging.level")

    console = merged.get("console") or {}
    if not isinstance(console, dict):
        raise LoggingConfigError("logging.console must be a dict")
    console_level = console.get("level", "WARNING")
    console["level"] = _validate_level(console_level, "logging.console.level")
    console["enabled"] = bool(console.get("enabled", False))
    merged["console"] = console

    directory = merged.get("directory", "./logs")
    raw_filename = merged.get("filename", "application.log")
    if not isinstance(raw_filename, str):
        raise LoggingConfigError("logging.filename must be a string")
    normalized_name = raw_filename.replace("\\", "/")
    if ".." in normalized_name.split("/") or normalized_name.startswith("/"):
        raise LoggingConfigError("logging.filename must not contain path traversal")
    filename = os.path.basename(raw_filename)
    if not filename or filename in (".", ".."):
        raise LoggingConfigError("logging.filename must be a valid file name")

    if base_dir is None:
        base_dir = os.getcwd()
    base_dir = os.path.abspath(base_dir)

    log_dir = resolve_path(directory, base_dir, "logging.directory")
    merged["directory"] = log_dir
    merged["filename"] = os.path.basename(filename)
    merged["base_dir"] = base_dir

    rotation = merged.get("rotation") or {}
    if not isinstance(rotation, dict):
        raise LoggingConfigError("logging.rotation must be a dict")
    rotation["enabled"] = bool(rotation.get("enabled", False))
    mode = str(rotation.get("mode", "DAILY")).upper()
    if mode not in ROTATION_MODES:
        raise LoggingConfigError(
            "logging.rotation.mode must be one of %s" % (ROTATION_MODES,)
        )
    rotation["mode"] = mode
    interval_days = rotation.get("interval_days", 7)
    if not isinstance(interval_days, int) or isinstance(interval_days, bool):
        raise LoggingConfigError("logging.rotation.interval_days must be a positive int")
    if interval_days < 1:
        raise LoggingConfigError("logging.rotation.interval_days must be >= 1")
    rotation["interval_days"] = interval_days
    rotation["compress"] = bool(rotation.get("compress", True))
    level = rotation.get("compression_level", 6)
    if not isinstance(level, int) or isinstance(level, bool):
        raise LoggingConfigError("logging.rotation.compression_level must be int 1-9")
    if level < 1 or level > 9:
        raise LoggingConfigError("logging.rotation.compression_level must be 1-9")
    rotation["compression_level"] = level
    merged["rotation"] = rotation

    retention = merged.get("retention") or {}
    if not isinstance(retention, dict):
        raise LoggingConfigError("logging.retention must be a dict")
    retention["enabled"] = bool(retention.get("enabled", False))
    days = retention.get("days", 90)
    if not isinstance(days, int) or isinstance(days, bool):
        raise LoggingConfigError("logging.retention.days must be a positive int")
    if days < 1:
        raise LoggingConfigError("logging.retention.days must be >= 1")
    retention["days"] = days
    retention["cleanup_on_startup"] = bool(retention.get("cleanup_on_startup", True))
    merged["retention"] = retention

    security = merged.get("security") or {}
    if not isinstance(security, dict):
        raise LoggingConfigError("logging.security must be a dict")
    security["redact_sensitive_data"] = bool(
        security.get("redact_sensitive_data", True)
    )
    fields = security.get("redact_fields") or []
    if not isinstance(fields, (list, tuple)):
        raise LoggingConfigError("logging.security.redact_fields must be a list")
    security["redact_fields"] = list(fields)
    merged["security"] = security

    merged["enabled"] = bool(merged.get("enabled", True))
    return merged


def validate_logging_config(config, base_dir=None):
    return normalize_logging_config(config, base_dir=base_dir)

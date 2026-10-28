"""Validated logging configuration.

``load_config(section, base_dir)`` turns the application's ``logging`` section into a
``LoggingConfig``. It never modifies the dict it is given, rejects unknown keys (typos
must not silently change retention/rotation), and resolves paths safely.
"""
import os
import re
import sys
from datetime import datetime, timedelta, timezone

# Thailand has no DST, so a fixed offset is exact and avoids zoneinfo (Python 3.9+).
TZ = timezone(timedelta(hours=7), "Asia/Bangkok")

ARCHIVE_DIR_NAME = "archive"
STATE_DIR_NAME = ".logging_state"
LEVELS = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
ROTATION_MODES = ("DAILY", "INTERVAL_DAYS")
# Always redacted; user supplied ``redact_fields`` are added to these, never replace them.
# Matching is by substring of the field name, so "token" also covers "access_token".
DEFAULT_REDACT_FIELDS = (
    "password", "passwd", "token", "authorization", "api_key",
    "secret", "credentials", "private_key",
)
FORBIDDEN_DIRS = ("/etc", "/bin", "/sbin", "/usr", "/boot", "/dev", "/proc", "/sys", "/lib", "/lib64")


class ConfigError(ValueError):
    """The logging configuration is invalid."""


class LoggingSetupError(RuntimeError):
    """Logging could not be started (e.g. the log directory is not writable)."""


_TOP = ("enabled", "level", "directory", "filename", "allowed_roots",
        "console", "rotation", "retention", "security")
_CONSOLE = ("enabled", "level")
_ROTATION = ("enabled", "mode", "interval_days", "anchor_date", "compress", "compression_level")
_RETENTION = ("enabled", "days", "cleanup_on_startup")
_SECURITY = ("redact_sensitive_data", "redact_fields")


# ---------------------------------------------------------------- validators
def _bool(value, path):
    if not isinstance(value, bool):
        raise ConfigError("%s must be true or false, got %r" % (path, value))
    return value


def _int(value, path, low=1, high=None):
    # bool is an int subclass; True must not pass as "1".
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("%s must be an integer, got %r" % (path, value))
    if value < low or (high is not None and value > high):
        rng = ">= %d" % low if high is None else "between %d and %d" % (low, high)
        raise ConfigError("%s must be %s, got %r" % (path, rng, value))
    return value


def _level(value, path):
    if not isinstance(value, str) or value.upper() not in LEVELS:
        raise ConfigError("%s must be one of %s, got %r" % (path, ", ".join(sorted(LEVELS, key=LEVELS.get)), value))
    return value.upper()


def _mode(value, path):
    if not isinstance(value, str) or value.upper() not in ROTATION_MODES:
        raise ConfigError("%s must be one of %s, got %r" % (path, ", ".join(ROTATION_MODES), value))
    return value.upper()


def _date(value, path):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise ConfigError("%s must be a date like 2026-10-07, got %r" % (path, value))


def _str_list(value, path):
    if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ConfigError("%s must be a list of non-empty strings" % path)
    return tuple(v.strip() for v in value)


def _filename(value, path):
    if (not isinstance(value, str) or not value or value in (".", "..")
            or os.path.basename(value) != value or "\\" in value or "\x00" in value
            or len(value) > 200 or value in (ARCHIVE_DIR_NAME, STATE_DIR_NAME)):
        raise ConfigError("%s must be a plain file name (no path separators, '..' or reserved names), got %r"
                          % (path, value))
    return value


def _check_keys(section, name, allowed):
    unknown = sorted(str(k) for k in set(section) - set(allowed))
    if unknown:
        hint = ""
        if name == "logging" and "application" in unknown:
            hint = " (pass config['logging'], not the whole application config)"
        raise ConfigError("unknown key(s) in %s: %s; allowed: %s%s"
                          % (name, ", ".join(unknown), ", ".join(allowed), hint))


def _section(parent, key, allowed):
    value = parent.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError("logging.%s must be an object" % key)
    _check_keys(value, "logging." + key, allowed)
    return value


def _get(section, key, default, check, path):
    if section.get(key) is None:
        return default
    return check(section[key], "%s.%s" % (path, key))


# ---------------------------------------------------------------- paths
def default_base_dir():
    """Directory of the running application script, never the current working directory
    (a cron job's CWD is usually $HOME)."""
    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    if main_file:
        return os.path.dirname(os.path.abspath(main_file))
    if sys.argv and sys.argv[0]:
        return os.path.dirname(os.path.abspath(sys.argv[0]))
    return os.getcwd()


def _inside(path, root):
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _resolve_directory(value, base, allowed_roots):
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ConfigError("logging.directory must be a non-empty string, got %r" % (value,))
    value = os.path.expanduser(value)
    if os.path.isabs(value):
        path = os.path.normpath(value)
    else:
        path = os.path.normpath(os.path.join(base, value))
        # Lexical check on purpose: a symlinked "logs" -> /data/logs is a normal server layout.
        if not _inside(path, base):
            raise ConfigError("logging.directory %r escapes the application base directory %s" % (value, base))
    real = os.path.realpath(path)
    if real == os.sep or any(_inside(real, bad) for bad in FORBIDDEN_DIRS):
        raise ConfigError("logging.directory %s is a protected system directory" % real)
    if allowed_roots and not any(_inside(real, os.path.realpath(r)) for r in allowed_roots):
        raise ConfigError("logging.directory %s is outside allowed_roots %s" % (real, list(allowed_roots)))
    return path


# ---------------------------------------------------------------- archive naming
def archive_regex(stem):
    """Matches ``<stem>.<start>_<end>[.<n>].log[.gz]`` and nothing belonging to another stem."""
    return re.compile(r"^%s\.(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})(?:\.(\d+))?\.log(?:\.gz)?$" % re.escape(stem))


def archive_basename(stem, start, end, n=0):
    return "%s.%s_%s%s.log" % (stem, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"),
                               ".%d" % n if n else "")


# ---------------------------------------------------------------- config object
class LoggingConfig(object):
    """Plain attribute holder produced by ``load_config``."""

    @property
    def log_path(self):
        return os.path.join(self.directory, self.filename)

    @property
    def archive_dir(self):
        return os.path.join(self.directory, ARCHIVE_DIR_NAME)

    @property
    def state_dir(self):
        return os.path.join(self.directory, STATE_DIR_NAME)

    @property
    def state_path(self):
        return os.path.join(self.state_dir, self.stem + ".rotation.json")

    @property
    def lock_path(self):
        return os.path.join(self.state_dir, self.stem + ".lock")

    @property
    def rot_interval(self):
        return 1 if self.rot_mode == "DAILY" else self.interval_days

    def signature(self):
        """Stable text form used by setup_logging() to detect an unchanged configuration."""
        return repr(sorted(vars(self).items()))


def load_config(raw, base_dir=None):
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("logging config must be an object/dict (the 'logging' section)")
    _check_keys(raw, "logging", _TOP)
    console = _section(raw, "console", _CONSOLE)
    rotation = _section(raw, "rotation", _ROTATION)
    retention = _section(raw, "retention", _RETENTION)
    security = _section(raw, "security", _SECURITY)

    base = os.path.abspath(base_dir if base_dir is not None else default_base_dir())
    cfg = LoggingConfig()
    cfg.enabled = _get(raw, "enabled", True, _bool, "logging")
    cfg.level_name = _get(raw, "level", "INFO", _level, "logging")
    cfg.level = LEVELS[cfg.level_name]
    cfg.filename = _get(raw, "filename", "app.log", _filename, "logging")
    cfg.stem = os.path.splitext(cfg.filename)[0] or cfg.filename
    cfg.allowed_roots = _get(raw, "allowed_roots", (), _str_list, "logging")
    cfg.directory = _resolve_directory(raw.get("directory") if raw.get("directory") is not None else "./logs",
                                       base, cfg.allowed_roots)

    cfg.console_enabled = _get(console, "enabled", False, _bool, "logging.console")
    cfg.console_level_name = _get(console, "level", "WARNING", _level, "logging.console")
    cfg.console_level = LEVELS[cfg.console_level_name]

    cfg.rot_enabled = _get(rotation, "enabled", True, _bool, "logging.rotation")
    cfg.rot_mode = _get(rotation, "mode", "DAILY", _mode, "logging.rotation")
    cfg.interval_days = _get(rotation, "interval_days", 7, _int, "logging.rotation")
    cfg.anchor_date = _get(rotation, "anchor_date", None, _date, "logging.rotation")
    cfg.compress = _get(rotation, "compress", True, _bool, "logging.rotation")
    cfg.compression_level = _get(rotation, "compression_level", 6,
                                 lambda v, p: _int(v, p, 1, 9), "logging.rotation")

    cfg.ret_enabled = _get(retention, "enabled", True, _bool, "logging.retention")
    cfg.ret_days = _get(retention, "days", 90, _int, "logging.retention")
    cfg.ret_cleanup_on_startup = _get(retention, "cleanup_on_startup", True, _bool, "logging.retention")

    cfg.redact_enabled = _get(security, "redact_sensitive_data", True, _bool, "logging.security")
    extra = _get(security, "redact_fields", (), _str_list, "logging.security")
    cfg.redact_fields = tuple(sorted(set(DEFAULT_REDACT_FIELDS) | set(f.lower() for f in extra)))
    return cfg

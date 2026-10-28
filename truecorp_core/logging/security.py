"""Sensitive data redaction for log messages and structured fields."""

from __future__ import unicode_literals

import re

DEFAULT_REDACT_FIELDS = (
    "password",
    "passwd",
    "pwd",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "auth",
    "api_key",
    "apikey",
    "secret",
    "credentials",
    "private_key",
)

REDACTED_PLACEHOLDER = "***REDACTED***"

# Key=value patterns in free text (case-insensitive keys).
_KV_PATTERN = re.compile(
    r"(?i)\b("
    + "|".join(re.escape(k) for k in DEFAULT_REDACT_FIELDS)
    + r")\s*=\s*([^\s]+)"
)

# Bearer / Basic headers in text.
_AUTH_HEADER_PATTERN = re.compile(
    r"(?i)(authorization\s*[:=]\s*)([^\s,;]+)",
)
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)([^\s]+)")


def normalize_redact_fields(fields):
    if not fields:
        return list(DEFAULT_REDACT_FIELDS)
    normalized = []
    seen = set()
    for item in fields:
        key = str(item).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(key)
    return normalized


def is_sensitive_field(name):
    if name is None:
        return False
    lowered = str(name).strip().lower()
    if lowered in DEFAULT_REDACT_FIELDS:
        return True
    for token in ("password", "token", "secret", "authorization", "credential", "api_key"):
        if token in lowered:
            return True
    return False


def redact_value(value):
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return REDACTED_PLACEHOLDER


def redact_mapping(mapping, redact_fields=None):
    if not mapping:
        return {}
    fields = normalize_redact_fields(redact_fields)
    field_set = set(fields)
    result = {}
    for key, value in mapping.items():
        key_str = str(key)
        lowered = key_str.lower()
        if lowered in field_set or is_sensitive_field(lowered):
            result[key_str] = redact_value(value)
        else:
            result[key_str] = value
    return result


def redact_text(message, redact_fields=None):
    if message is None:
        return ""
    if not isinstance(message, str):
        message = str(message)
    if not message:
        return message

    def _kv_repl(match):
        return match.group(1) + "=" + REDACTED_PLACEHOLDER

    text = _KV_PATTERN.sub(_kv_repl, message)

    def _bearer_repl(match):
        return match.group(1) + REDACTED_PLACEHOLDER

    text = _BEARER_PATTERN.sub(_bearer_repl, text)

    def _auth_repl(match):
        return match.group(1) + REDACTED_PLACEHOLDER

    text = _AUTH_HEADER_PATTERN.sub(_auth_repl, text)
    return text


def sanitize_log_value(value):
    """Escape control characters and newlines in a single log field value."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    value = value.replace("\\", "\\\\")
    value = value.replace("\r", "\\r")
    value = value.replace("\n", "\\n")
    value = value.replace("\t", "\\t")
    for code in range(0, 32):
        if code in (9, 10, 13):
            continue
        ch = chr(code)
        if ch in value:
            value = value.replace(ch, "\\x%02x" % code)
    return value

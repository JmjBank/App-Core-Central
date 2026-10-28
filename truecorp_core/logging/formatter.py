"""Plain-text log formatter with Asia/Bangkok timestamp and key-value context."""

from __future__ import unicode_literals

import logging
import os
import socket
import sys
from datetime import datetime, timedelta, tzinfo

from truecorp_core.logging.context import CONTEXT_KEYS
from truecorp_core.logging.security import (
    redact_mapping,
    redact_text,
    sanitize_log_value,
)


class _BangkokTZ(tzinfo):
    """Fixed UTC+7 — Asia/Bangkok has no DST."""

    def utcoffset(self, dt):
        return timedelta(hours=7)

    def tzname(self, dt):
        return "+07"

    def dst(self, dt):
        return timedelta(0)


BANGKOK_TZ = _BangkokTZ()

ORDERED_CONTEXT_KEYS = (
    "tracking_id",
    "async_id",
    "batch_id",
    "event",
    "step",
    "duration_ms",
    "hostname",
    "pid",
)


class TrueCorpFormatter(logging.Formatter):
    def __init__(
        self,
        application_name="APP",
        redact_sensitive_data=True,
        redact_fields=None,
        include_hostname=False,
        include_pid=False,
    ):
        super(TrueCorpFormatter, self).__init__()
        self.application_name = application_name or "APP"
        self.redact_sensitive_data = bool(redact_sensitive_data)
        self.redact_fields = redact_fields or []
        self.include_hostname = include_hostname
        self.include_pid = include_pid
        self._default_hostname = socket.gethostname()

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created, BANGKOK_TZ)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    def _format_context_suffix(self, record):
        parts = []
        for key in ORDERED_CONTEXT_KEYS:
            value = getattr(record, key, None)
            if value is None and key == "hostname" and self.include_hostname:
                value = self._default_hostname
            if value is None and key == "pid" and self.include_pid:
                value = os.getpid()
            if value is None or value == "":
                continue
            if self.redact_sensitive_data:
                mapping = redact_mapping({key: value}, self.redact_fields)
                value = mapping.get(key, value)
            safe = sanitize_log_value(value)
            parts.append("%s=%s" % (key, safe))

        extra = {}
        for key, value in record.__dict__.items():
            if key.startswith("_"):
                continue
            if key in (
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
                "run_id",
            ):
                continue
            if key in CONTEXT_KEYS or key in ORDERED_CONTEXT_KEYS:
                continue
            extra[key] = value

        if extra:
            if self.redact_sensitive_data:
                extra = redact_mapping(extra, self.redact_fields)
            for key in sorted(extra.keys()):
                value = extra[key]
                if value is None or value == "":
                    continue
                parts.append("%s=%s" % (key, sanitize_log_value(value)))
        return " ".join(parts)

    def format(self, record):
        message = record.getMessage()
        if self.redact_sensitive_data:
            message = redact_text(message, self.redact_fields)

        run_id = getattr(record, "run_id", None)
        run_display = run_id if run_id not in (None, "") else "-"

        suffix = self._format_context_suffix(record)
        if suffix:
            body = "%s %s" % (message, suffix)
        else:
            body = message

        line = "%s [%s] [%s] [%s] %s" % (
            self.formatTime(record),
            record.levelname,
            self.application_name,
            run_display,
            body,
        )

        if record.exc_info:
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            if self.redact_sensitive_data:
                exc_text = redact_text(record.exc_text, self.redact_fields)
            else:
                exc_text = record.exc_text
            line = line + "\n" + exc_text
        if record.stack_info:
            line = line + "\n" + record.stack_info
        return line

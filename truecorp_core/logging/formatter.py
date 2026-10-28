"""Plain-text formatter (the only format in v0.1.0).

    2026-10-28 15:00:03 [INFO] [APP_CANCEL_5534] [RUN-001] message tracking_id=ABC123 event=X duration_ms=1250

Timestamps are Asia/Bangkok wall-clock time. Missing run id renders as ``-``; missing
optional fields are simply omitted, so the formatter cannot fail on absent context.
"""
import logging
import re
from datetime import datetime

from .config import TZ
from .context import get_run_context
from .security import quote_value, sanitize, to_text

PREFIX = "truecorp."
_KNOWN = ("tracking_id", "async_id", "batch_id", "event", "step", "duration_ms", "hostname", "pid")
_STD = frozenset(logging.LogRecord("n", 20, "p", 1, "m", (), None).__dict__) | {"message", "asctime"}
_BAD_KEY = re.compile(r"[^\w.\-]")


class TextFormatter(logging.Formatter):
    def __init__(self, redactor=None):
        logging.Formatter.__init__(self)
        self._redactor = redactor

    def _redact(self, text):
        return self._redactor.redact_text(text) if self._redactor else text

    def _fields(self, record):
        fields = {k: v for k, v in get_run_context().items() if k != "run_id"}
        for key, value in record.__dict__.items():  # logger.info(..., extra={...}) wins over context
            if key not in _STD and key != "run_id" and not key.startswith("_"):
                fields[key] = value
        keys = [k for k in _KNOWN if k in fields] + sorted(k for k in fields if k not in _KNOWN)
        parts = []
        for key in keys:
            value = fields[key]
            text = (self._redactor.redact_field(key, value) if self._redactor else to_text(value))
            parts.append("%s=%s" % (_BAD_KEY.sub("_", key), quote_value(text)))
        return parts

    def format(self, record):
        run_id = record.__dict__.get("run_id") or get_run_context().get("run_id")
        name = record.name[len(PREFIX):] if record.name.startswith(PREFIX) else record.name
        stamp = datetime.fromtimestamp(record.created, TZ).strftime("%Y-%m-%d %H:%M:%S")
        fields = self._fields(record)

        exc_text = None
        if record.exc_info and record.exc_info[0] is not None:
            fields.append("error_type=%s" % quote_value(record.exc_info[0].__name__))
            exc_text = self.formatException(record.exc_info)  # not cached on the record: handlers differ

        head = "%s [%s] [%s] [%s]" % (stamp, sanitize(record.levelname), sanitize(name),
                                      sanitize(to_text(run_id)) if run_id else "-")
        body = [sanitize(self._redact(record.getMessage()))] + fields
        line = " ".join([head] + [p for p in body if p])

        extra_blocks = [t for t in (exc_text, record.stack_info) if t]
        for block in extra_blocks:
            # Every continuation line is indented, so text inside an exception message can
            # never look like the start of a new log record.
            for text_line in self._redact(block).splitlines():
                line += "\n    " + sanitize(text_line)
        return line

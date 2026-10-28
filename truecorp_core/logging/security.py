"""Sensitive-data redaction and log-line forgery protection.

Redaction is best effort and pattern based. It does NOT detect every secret (see
README "Security"): free text such as ``password=my secret pass`` (unquoted, with
spaces), secrets without a recognisable field name, and Oracle-style ``user/pass@tns``
strings are not caught. Never log credentials on purpose.
"""
import re

REDACTED = "[REDACTED]"

_SCHEMES = r"(?:bearer|basic|digest|negotiate|ntlm|token)"
_VALUE = r"""(?:%s\s+)?(?:"[^"]*"|'[^']*'|[^\s,;&"']+)""" % _SCHEMES
_PEM = re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?(?:-----END [A-Z0-9 ]*PRIVATE KEY-----|$)", re.S)
_URL_CRED = re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:)[^@\s/]+@", re.I)
_BEARER = re.compile(r"\bBearer\s+(?!\[REDACTED)[A-Za-z0-9\-._~+/]+=*", re.I)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]*")

_CONTROL = re.compile(u"[\x00-\x1f\x7f\x85  ]")
_NEEDS_QUOTE = re.compile(u'[\\s="\\\\\x00-\x1f\x7f]')
_NAMED = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}


def to_text(value):
    try:
        return value if isinstance(value, str) else str(value)
    except Exception:  # noqa: a broken __str__ must never break logging
        return "<unprintable %s>" % type(value).__name__


def _escape_one(match):
    ch = match.group(0)
    if ch in _NAMED:
        return _NAMED[ch]
    return "\\x%02x" % ord(ch) if ord(ch) < 256 else "\\u%04x" % ord(ch)


def sanitize(text):
    """Escape newlines and other control characters so one event is always one line."""
    return _CONTROL.sub(_escape_one, text)


def quote_value(text):
    """Render a key=value value: quoted (with escapes) only when it needs to be."""
    needs = text == "" or _NEEDS_QUOTE.search(text) is not None
    if needs:
        text = text.replace("\\", "\\\\").replace('"', '\\"')
    text = sanitize(text)
    return '"%s"' % text if needs else text


class Redactor(object):
    def __init__(self, fields):
        names = sorted({str(f).strip().lower() for f in fields if str(f).strip()}, key=len, reverse=True)
        # "api_key" also matches api-key / apikey; names match as substrings (access_token, db_password).
        alt = "|".join("[_\\-]?".join(re.escape(p) for p in n.split("_")) for n in names)
        self._key_re = re.compile("(?:%s)" % alt, re.I) if alt else None
        self._kv_re = (re.compile(r"""\b([\w.\-]*(?:%s)[\w.\-]*)(\s*["']?\s*[:=]\s*)(%s)""" % (alt, _VALUE), re.I)
                       if alt else None)

    def redact_text(self, text):
        text = _PEM.sub("[REDACTED_PRIVATE_KEY]", text)
        text = _URL_CRED.sub(r"\1" + REDACTED + "@", text)
        if self._kv_re is not None:
            text = self._kv_re.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
        text = _BEARER.sub("Bearer " + REDACTED, text)
        return _JWT.sub("[REDACTED_JWT]", text)

    def redact_field(self, key, value):
        """Structured field: redact by field name first, then scan the value text."""
        if self._key_re is not None and self._key_re.search(key):
            return REDACTED
        return self.redact_text(to_text(value))

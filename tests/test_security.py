"""Security redaction and sanitization tests."""

from __future__ import unicode_literals

import unittest

from truecorp_core.logging.security import (
    redact_text,
    redact_mapping,
    sanitize_log_value,
)


class TestSecurity(unittest.TestCase):
    def test_password_redaction(self):
        text = redact_text("login password=SuperSecret123 ok")
        self.assertIn("password=***REDACTED***", text)
        self.assertNotIn("SuperSecret123", text)

    def test_authorization_redaction(self):
        text = redact_text("Authorization: Bearer abcdef")
        self.assertNotIn("abcdef", text)
        self.assertIn("REDACTED", text)

    def test_token_redaction_mapping(self):
        data = redact_mapping({"access_token": "XYZ", "event": "OK"})
        self.assertEqual(data["access_token"], "***REDACTED***")
        self.assertEqual(data["event"], "OK")

    def test_newline_sanitization(self):
        safe = sanitize_log_value("line1\nline2")
        self.assertNotIn("\n", safe)
        self.assertIn("\\n", safe)

    def test_control_character_sanitization(self):
        safe = sanitize_log_value("a\x00b")
        self.assertIn("\\x00", safe)


if __name__ == "__main__":
    unittest.main()

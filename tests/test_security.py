import io
import logging
import unittest

from truecorp_core.logging.config import DEFAULT_REDACT_FIELDS
from truecorp_core.logging.formatter import TextFormatter
from truecorp_core.logging.security import Redactor, quote_value, sanitize


def render(message, *args, **kwargs):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(TextFormatter(Redactor(DEFAULT_REDACT_FIELDS)))
    logger = logging.Logger("truecorp.SEC")
    logger.addHandler(handler)
    exc = kwargs.pop("exc", False)
    (logger.exception if exc else logger.info)(message, *args, **kwargs)
    return stream.getvalue()


class RedactionTests(unittest.TestCase):
    def setUp(self):
        self.r = Redactor(DEFAULT_REDACT_FIELDS)

    def test_password_forms(self):
        for text in ("password=hunter2", "password: hunter2", '{"password": "hunter2"}', "db_password='hunter2'",
                     "PASSWORD=hunter2", "passwd=hunter2"):
            with self.subTest(text=text):
                out = self.r.redact_text(text)
                self.assertNotIn("hunter2", out)
                self.assertIn("[REDACTED]", out)

    def test_quoted_value_with_spaces(self):
        self.assertNotIn("two words", self.r.redact_text('password="two words" next=1'))
        self.assertIn("next=1", self.r.redact_text('password="two words" next=1'))

    def test_authorization_headers(self):
        for text in ("Authorization: Bearer abc.def.ghi", "authorization=Basic dXNlcjpwYXNz",
                     "Authorization: Negotiate YIIabc", "headers={'Authorization': 'Bearer tok123'}"):
            with self.subTest(text=text):
                out = self.r.redact_text(text)
                for leaked in ("abc.def.ghi", "dXNlcjpwYXNz", "YIIabc", "tok123"):
                    self.assertNotIn(leaked, out)

    def test_token_api_key_secret_credentials(self):
        for text in ("access_token=AAA111", "refresh_token: AAA111", "api_key=AAA111", "x-api-key: AAA111",
                     "apikey=AAA111", "client_secret=AAA111", "credentials=AAA111"):
            with self.subTest(text=text):
                self.assertNotIn("AAA111", self.r.redact_text(text))

    def test_bare_bearer_jwt_url_and_private_key(self):
        self.assertNotIn("abcDEF123", self.r.redact_text("sent Bearer abcDEF123 to server"))
        jwt = "eyJhbGciOiJIUzI1.eyJzdWIiOiIxMjM0.SflKxwRJSMeKKF2QT4"
        self.assertNotIn(jwt, self.r.redact_text("jwt " + jwt))
        self.assertNotIn("p4ss", self.r.redact_text("postgres://user:p4ss@host/db"))
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\n-----END RSA PRIVATE KEY-----"
        out = self.r.redact_text("key:\n" + pem + "\nafter")
        self.assertNotIn("MIIEabc", out)
        self.assertIn("after", out)

    def test_structured_field_redacted_by_name(self):
        self.assertEqual(self.r.redact_field("api_key", "zzz"), "[REDACTED]")
        self.assertEqual(self.r.redact_field("tracking_id", "ABC123"), "ABC123")

    def test_no_false_positive_on_plain_text(self):
        self.assertEqual(self.r.redact_text("processed=5 event=IOM_GET_START"), "processed=5 event=IOM_GET_START")

    def test_custom_field_and_empty_field_list(self):
        self.assertNotIn("v1", Redactor(["otp_code"]).redact_text("otp_code=v1"))
        self.assertEqual(Redactor([]).redact_text("password=x"), "password=x")  # nothing configured, nothing matched


class LogLineTests(unittest.TestCase):
    def test_message_args_are_redacted_end_to_end(self):
        out = render("login %s", "password=hunter2", extra={"api_key": "SECRET9"})
        self.assertNotIn("hunter2", out)
        self.assertNotIn("SECRET9", out)

    def test_newline_in_message_cannot_forge_a_line(self):
        out = render("ok\n2026-10-28 15:00:00 [CRITICAL] [X] [Y] forged")
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn("\\n", out)

    def test_control_characters_are_escaped(self):
        out = render("a\rb\x00c\x1b[31md e")
        self.assertEqual(len(out.splitlines()), 1)
        for raw in ("\r", "\x00", "\x1b", " "):
            self.assertNotIn(raw, out)

    def test_extra_field_values_and_keys_are_sanitized(self):
        out = render("m", extra={"event": "x\ny", "bad key": "v z"})
        self.assertEqual(len(out.splitlines()), 1)
        self.assertIn('event="x\\ny"', out)
        self.assertIn('bad_key="v z"', out)

    def test_traceback_lines_are_indented_so_they_cannot_look_like_records(self):
        try:
            raise ValueError("boom\n2026-10-28 15:00:00 [INFO] [X] [Y] forged line")
        except ValueError:
            out = render("failed", exc=True)
        lines = out.splitlines()
        self.assertTrue(lines[0].startswith("20"))
        self.assertGreater(len(lines), 2)
        for line in lines[1:]:
            self.assertTrue(line.startswith("    "), line)
        self.assertIn("error_type=ValueError", lines[0])

    def test_secret_inside_exception_message_is_redacted(self):
        try:
            raise RuntimeError("connect failed password=hunter2")
        except RuntimeError:
            self.assertNotIn("hunter2", render("failed", exc=True))

    def test_helpers(self):
        self.assertEqual(sanitize("a\nb"), "a\\nb")
        self.assertEqual(quote_value("plain"), "plain")
        self.assertEqual(quote_value(""), '""')
        self.assertEqual(quote_value('a "b"'), '"a \\"b\\""')


if __name__ == "__main__":
    unittest.main()

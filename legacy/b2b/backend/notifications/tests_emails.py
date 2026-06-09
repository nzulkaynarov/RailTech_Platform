"""Rendering smoke tests for every email template.

A TemplateDoesNotExist / VariableDoesNotExist crash at runtime is far worse
than a failing test here — these tests are the CI gate that keeps templates
honest as they evolve.
"""

from django.conf import settings
from django.core import mail
from django.test import SimpleTestCase, TestCase, override_settings

from notifications.emails import EmailDeliveryError, _render_bodies, send_templated_email
from notifications.models import EmailLog

TEMPLATE_CASES = [
    (
        "setup_password",
        {"first_name": "Алиса", "setup_url": "https://app.example.com/setup?token=abc"},
    ),
    (
        "invite_member",
        {"company_name": "Alpha LLC", "setup_url": "https://app.example.com/setup?token=xyz"},
    ),
    (
        "kyc_verified",
        {
            "company_name": "Alpha LLC",
            "company_inn": "123456789",
            "level_code": "L2_VERIFIED",
            "frontend_url": "https://app.example.com",
        },
    ),
    (
        "kyc_verified",
        {
            "company_name": "Alpha LLC",
            "company_inn": "123456789",
            "level_code": "L3_CONTRACTED",
            "frontend_url": "https://app.example.com",
        },
    ),
    (
        "role_application_approved",
        {
            "company_name": "Alpha LLC",
            "requested_type_name": "Поставщик",
            "trial_granted": True,
            "frontend_url": "https://app.example.com",
        },
    ),
    (
        "role_application_rejected",
        {
            "company_name": "Alpha LLC",
            "requested_type_name": "Производитель",
            "review_notes": "Не хватает устава.",
            "frontend_url": "https://app.example.com",
        },
    ),
]


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class TemplatedEmailRenderingTests(TestCase):
    """Each template renders + sends without errors and logs to EmailLog."""

    def test_channels_are_configured(self):
        self.assertIn("transactional", settings.EMAIL_CHANNELS)
        self.assertIn("marketing", settings.EMAIL_CHANNELS)
        self.assertIn("system", settings.EMAIL_CHANNELS)
        for ch, cfg in settings.EMAIL_CHANNELS.items():
            self.assertIn("backend", cfg, f"channel {ch} missing 'backend'")
            self.assertIn("from_email", cfg, f"channel {ch} missing 'from_email'")

    def test_all_templates_render_and_send(self):
        for template, ctx in TEMPLATE_CASES:
            with self.subTest(template=template, level=ctx.get("level_code")):
                mail.outbox = []
                log = send_templated_email(
                    template,
                    ctx,
                    to=["recipient@example.com"],
                    channel="transactional",
                )
                self.assertEqual(len(mail.outbox), 1)
                msg = mail.outbox[0]
                self.assertTrue(msg.subject, "subject must be non-empty")
                self.assertTrue(msg.body, "plain body must be non-empty")
                # HTML alternative attached
                self.assertTrue(
                    any(alt[1] == "text/html" for alt in msg.alternatives),
                    f"{template}: no HTML alternative",
                )
                self.assertEqual(log.status, EmailLog.STATUS_SENT)
                self.assertEqual(log.template, template)
                self.assertEqual(log.to_emails, ["recipient@example.com"])

    def test_unknown_channel_raises(self):
        with self.assertRaises(ValueError):
            send_templated_email(
                "setup_password",
                {"first_name": "X", "setup_url": "https://x"},
                to=["a@b.com"],
                channel="does_not_exist",
            )

    def test_empty_recipients_rejected(self):
        with self.assertRaises(ValueError):
            send_templated_email(
                "setup_password",
                {"first_name": "X", "setup_url": "https://x"},
                to=[],
            )

    def test_transport_failure_records_failed_log(self):
        broken = {
            **settings.EMAIL_CHANNELS,
            "transactional": {
                **settings.EMAIL_CHANNELS["transactional"],
                # Force a send-time failure via a non-existent module path.
                "backend": "notifications.tests_emails._BrokenBackend",
            },
        }
        with override_settings(EMAIL_CHANNELS=broken):
            with self.assertRaises(EmailDeliveryError):
                send_templated_email(
                    "setup_password",
                    {"first_name": "X", "setup_url": "https://x"},
                    to=["a@b.com"],
                )
        self.assertTrue(
            EmailLog.objects.filter(status=EmailLog.STATUS_FAILED).exists(),
            "failed attempt must be persisted for audit",
        )


class EmailLinkIntegrityTests(SimpleTestCase):
    """Regression guard for the &-escaping bug (2026-06-08).

    A setup/reset link '?uid=X&token=Y' must survive in the PLAIN-TEXT body as a
    clickable URL. Django auto-escaping turned '&' into '&amp;', which dropped the
    'token' query param and bounced users off the password page. The HTML body
    legitimately keeps '&amp;' (the browser decodes it on click). Pure rendering —
    no DB, no SMTP — so it can never flake on the mail backend.
    """

    # (template, context key holding a URL with a query string)
    LINK_TEMPLATES = [
        ("setup_password", "setup_url"),
        ("reset_password", "reset_url"),
        ("invite_member", "setup_url"),
    ]

    def test_plaintext_query_links_are_not_html_escaped(self):
        url = "https://b2b.railtech.uz/setup-password?uid=NDA&token=abc-123def"
        for template, url_key in self.LINK_TEMPLATES:
            with self.subTest(template=template):
                context = {"first_name": "Тест", "company_name": "Acme", url_key: url}
                _subject, text_body, html_body = _render_bodies(template, context)

                # Plain text: the raw URL stays intact, so the token is not lost.
                self.assertIn(url, text_body, f"{template}: plain-text link was mangled")
                self.assertNotIn("&amp;", text_body, f"{template}: plain text must not be HTML-escaped")
                self.assertIn("&token=", text_body, f"{template}: token param dropped from plain text")

                # HTML body: '&' is correctly entity-escaped inside the href.
                self.assertIn("&amp;token=", html_body, f"{template}: HTML href should escape '&'")

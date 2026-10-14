"""Rendering smoke tests for every email template.

A TemplateDoesNotExist / VariableDoesNotExist crash at runtime is far worse
than a failing test here — these tests are the CI gate that keeps templates
honest as they evolve.
"""

from django.conf import settings
from django.core import mail
from django.test import TestCase, override_settings

from notifications.emails import EmailDeliveryError, _render_bodies, send_templated_email
from notifications.models import EmailLog

TEMPLATE_CASES = [
    # ВСЕ бандлы писем: раньше в наборе было 5 из 17, и 12 шаблонов не рендерились
    # тестом вовсе — правка в них (в т.ч. разметка {% translate %} волной L2) ломала бы
    # отправку молча. Контексты заполнены целиком, чтобы проходились обе ветки условий.
    (
        "setup_password",
        {"first_name": "Алиса", "name": "Алиса", "setup_url": "https://app.example.com/setup?token=abc"},
    ),
    (
        "reset_password",
        {"first_name": "Алиса", "name": "Алиса", "reset_url": "https://app.example.com/reset?token=abc"},
    ),
    ("invite_member", {"company_name": "Alpha LLC", "setup_url": "https://app.example.com/setup?token=xyz"}),
    (
        "new_rfq_seller",
        {
            "deal_title": "Рельсы Р65",
            "buyer_name": "Beta LLC",
            "deal_url": "https://app.example.com/deal/1",
            "assigned": True,
        },
    ),
    (
        "new_rfq_seller",
        {
            "deal_title": "Рельсы Р65",
            "buyer_name": "Beta LLC",
            "deal_url": "https://app.example.com/deal/1",
            "assigned": False,
        },
    ),
    (
        "quote_sent",
        {
            "quote_number": "КП-2026-00042",
            "quote_version": 2,
            "recipient_name": "Пётр",
            "seller_name": "Alpha LLC",
            "total_incl_vat": "12 500 000 UZS",
            "valid_until": "31.12.2026",
            "public_link": "https://app.example.com/q/tok",
        },
    ),
    (
        "quote_acceptance_code",
        {"code": "123456", "expires_minutes": 15, "quote_number": "КП-2026-00042", "seller_name": "Alpha LLC"},
    ),
    (
        "quote_accepted_contact",
        {"quote_number": "КП-2026-00042", "contract_number": "CT-2026-00007", "seller_name": "Alpha LLC"},
    ),
    (
        "invoice_issued",
        {
            "invoice_number": "INV-2026-00001",
            "deal_title": "Рельсы Р65",
            "seller_name": "Alpha LLC",
            "total": "12 500 000 UZS",
            "due_date": "31.12.2026",
            "invoice_url": "https://app.example.com/invoices/1",
        },
    ),
    (
        "invoice_issued",
        {
            "invoice_number": "INV-2026-00001",
            "total": "12 500 000 UZS",
            "invoice_url": "https://app.example.com/invoices/1",
        },
    ),
    (
        "payment_received",
        {
            "invoice_number": "INV-2026-00001",
            "deal_title": "Рельсы Р65",
            "buyer_name": "Beta LLC",
            "amount": "5 000 000 UZS",
            "paid_total": "5 000 000 UZS",
            "total": "12 500 000 UZS",
            "is_fully_paid": False,
            "invoice_url": "https://app.example.com/invoices/1",
        },
    ),
    (
        "payment_received",
        {
            "invoice_number": "INV-2026-00001",
            "amount": "12 500 000 UZS",
            "paid_total": "12 500 000 UZS",
            "total": "12 500 000 UZS",
            "is_fully_paid": True,
            "invoice_url": "https://app.example.com/invoices/1",
        },
    ),
    (
        "payment_reminder",
        {
            "invoice_number": "INV-2026-00001",
            "deal_title": "Рельсы Р65",
            "seller_name": "Alpha LLC",
            "total": "12 500 000 UZS",
            "balance_due": "7 500 000 UZS",
            "due_date": "31.12.2026",
            "invoice_url": "https://app.example.com/invoices/1",
        },
    ),
    (
        "act_awaiting_acceptance",
        {
            "act_number": "ACT-2026-00003",
            "deal_title": "Рельсы Р65",
            "total": "12 500 000 UZS",
            "deal_url": "https://app.example.com/deal/1",
        },
    ),
    (
        "generated_document",
        {
            "document_number": "DOC-2026-00001",
            "document_title": "Гарантийное письмо",
            "company_name": "Alpha LLC",
            "public_link": "https://app.example.com/d/tok",
        },
    ),
]


def _locmem_channel() -> dict:
    """Тестовый канал: locmem-бэкенд, чтобы письма попадали в mail.outbox.

    Файл был написан ДО механики EMAIL_CHANNELS и никогда не собирался pytest'ом из-за
    имени tests_emails.py (уборка 02-08): канальный get_connection(backend=...) обходит
    подмену EMAIL_BACKEND тест-раннером, поэтому канал переопределяется явно.
    """
    return {
        "backend": "django.core.mail.backends.locmem.EmailBackend",
        "host": "",
        "port": 25,
        "username": "",
        "password": "",
        "use_tls": False,
        "from_email": "test@example.com",
    }


LOCMEM_CHANNELS = {ch: _locmem_channel() for ch in ("transactional", "marketing", "system")}


class _BrokenBackend:
    """Транспорт, падающий на send_messages, — для теста fault-барьера EmailLog(FAILED)."""

    def __init__(self, *args, **kwargs):
        pass

    def send_messages(self, messages):
        raise OSError("smtp down (test)")


@override_settings(EMAIL_CHANNELS=LOCMEM_CHANNELS)
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
                "backend": "notifications.tests.test_emails._BrokenBackend",
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


@override_settings(EMAIL_CHANNELS=LOCMEM_CHANNELS)
class EmailLinkIntegrityTests(TestCase):
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
        url = "https://erp.example.com/setup-password?uid=NDA&token=abc-123def"
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

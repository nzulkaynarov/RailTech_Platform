"""W18A-P1 (B-INB-6): ERP письма сама не шлёт — каждое письмо уходит событием `uz.railtech.erp.mail.requested.v1` почтовому
сервису CRM в той же транзакции, что и изменение; SMTP-соединений из ERP нет; вложения — по ссылке на объект хранилища
ERP; итог доставки (`uz.railtech.crm.mail.sent|failed.v1`) обновляет журнал писем ERP и итог отправки КП.
"""

from __future__ import annotations

import hashlib
import smtplib

import pytest
from django.core.mail import EmailMessage, send_mail
from django.db import transaction
from integration.tests import bus_support
from integration.tests.world import add_quote, make_company, make_deal
from rt_bus import default_registry
from rt_bus.django.models import Outbox

from core.models import EmailLog
from notifications import mail_bus
from notifications.emails import EmailDeliveryError, send_templated_email

pytestmark = pytest.mark.django_db

BUS_BACKEND = "notifications.bus_backend.BusEmailBackend"
PAIR_SECRET = "test-pair-secret-erp-crm"
VECTOR_KEY = "X9hy9oZT8E1lJ-2hJu430cg_YyaOednsYENWMNC0eSs="
VECTOR_TOKEN = (
    "gAAAAABq4eM8WhS2WIUSMWplzbr_UITssK3O1At4Ygmar1FG4W1-lZDUAIXhWsbPRFdrbcTSRM5FmFIkITYaVwH76wglyjXDzwB1w3Ygfrd_ZOw"
    "smf6o1XEbCMobtTyVu-1UXnDuOv6p6l1bPk2YPTNf8pnLAeyIg8RQvF9kqBPYhUl01NvN6GyyU2dcqlManzgcyDP9vpMnMqrLppPr-GlBNJnIfOaY"
    "3G7qS8BJ3krVXIjcUCxwF2i97pqVQtvaIQUIQuXfq5TB4Kl-BXmbtsVZRqsFD7X1CXHjBwbVnOxoZH0TiujuQhA0CggQu9rKIckB6F0mrUvDkLyca"
    "OPgSfr0ZaU-qoVZIgk9RKtIAf94qgZCSXA-KdAgk5uJDkIt-_0ZpsU-Lm_4ImHieR0YrjvLdo9XDvTwrA=="
)
VECTOR_PLAIN = {
    "text": "Здравствуйте! Ссылка: https://cabinet.example.com/auth/magic#token=abc",
    "html": "<p>Здравствуйте!</p>",
    "links": [
        {"url": "http://rustfs:9000/erp-temp/mail/x.pdf?X-Amz-Signature=00", "expires_at": "2026-10-29T09:15:00Z"}
    ],
}
CONTEXT = {"first_name": "Алиса", "setup_url": "https://erp.example.com/setup?uid=1&token=sEcReT"}


@pytest.fixture
def bus_mail(settings, monkeypatch):
    settings.EMAIL_BACKEND = BUS_BACKEND
    monkeypatch.setenv("RT_BUS_SECRET_ERP_CRM", PAIR_SECRET)
    bus_support.reset()


@pytest.fixture
def no_smtp(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("ERP не открывает SMTP-соединений (W18A-P1)")

    monkeypatch.setattr(smtplib.SMTP, "__init__", forbidden)
    monkeypatch.setattr(smtplib.SMTP_SSL, "__init__", forbidden)


class _FakeClient:
    def __init__(self, calls):
        self.calls = calls

    def generate_presigned_url(self, method, Params, ExpiresIn):  # noqa: N803 — сигнатура boto3
        self.calls.append((method, Params, ExpiresIn))
        return f"http://rustfs:9000/{Params['Bucket']}/{Params['Key']}?X-Amz-Signature=fake"


class _FakeTempStorage:
    """erp-temp: сохраняет байты в памяти, подписанная ссылка — как у boto3."""

    bucket_name = "erp-temp"

    def __init__(self):
        self.saved: dict[str, bytes] = {}
        self.calls: list = []
        self.bucket = type("B", (), {"meta": type("M", (), {"client": _FakeClient(self.calls)})()})()

    def save(self, name, content):
        self.saved[name] = content.read()
        return name

    def _normalize_name(self, name):
        return name


def mail_requests() -> list[dict]:
    rows = Outbox.objects.filter(type=mail_bus.MAIL_REQUESTED).order_by("created_at", "id")
    return [row.envelope for row in rows]


def opened(envelope: dict) -> dict:
    return mail_bus.open_content([PAIR_SECRET], envelope["data"]["content"]["ciphertext"])


# ── шифрование тела: общий формат ERP / EDS / CRM ─────────────────────────────────────────────────────


def test_content_key_and_cross_service_vector():
    assert mail_bus.content_key(PAIR_SECRET).decode() == VECTOR_KEY
    assert mail_bus.open_content(["другой секрет", PAIR_SECRET], VECTOR_TOKEN) == VECTOR_PLAIN


def test_seal_then_open_round_trip_and_wrong_secret_is_refused():
    token = mail_bus.seal_content(PAIR_SECRET, text="t", html=None, links=[])
    assert mail_bus.open_content([PAIR_SECRET], token) == {"text": "t", "html": None, "links": []}
    with pytest.raises(mail_bus.MailRequestError, match="MAIL_CONTENT_UNREADABLE"):
        mail_bus.open_content(["чужой"], token)


# ── письмо = событие outbox в транзакции изменения ────────────────────────────────────────────────────


def test_templated_email_is_one_bus_event_in_the_same_transaction(bus_mail, no_smtp):
    log = send_templated_email("setup_password", CONTEXT, to=["alice@example.com"], ref=("user", 5))
    [envelope] = mail_requests()
    bus_support.assert_matches_contract(envelope)
    data = envelope["data"]
    assert data["request_key"] == f"erp:email_log:{log.pk}" and envelope["subject"] == f"mail/erp:email_log:{log.pk}"
    assert data["purpose"] == "setup_password" and data["to"] == ["alice@example.com"] and data["notify"] is True
    assert data["ref"] == {"kind": "user", "id": "5"}
    assert "sEcReT" not in str(data), "одноразовая ссылка — только шифртекстом"
    body = opened(envelope)
    assert "token=sEcReT" in body["text"] and body["html"] and body["links"] == []
    assert log.status == EmailLog.STATUS_QUEUED and log.from_email == "crm"
    assert "sEcReT" not in log.body_text, "журнал ERP по-прежнему прячет токены (SEC-02)"


def test_rolled_back_change_leaves_neither_event_nor_log(bus_mail, no_smtp):
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            send_templated_email("setup_password", CONTEXT, to=["alice@example.com"])
            raise RuntimeError("изменение откатилось")
    assert mail_requests() == []
    assert not EmailLog.objects.exists()


def test_plain_send_mail_also_goes_through_the_bus_without_smtp(bus_mail, no_smtp):
    assert send_mail("Тема", "Текст", None, ["bob@example.com"], html_message="<b>HTML</b>") == 1
    message = EmailMessage("Копия", "Текст", to=["a@example.com"], cc=["b@example.com"], bcc=["c@example.com"])
    assert message.send() == 1
    first, second = mail_requests()
    for envelope in (first, second):
        bus_support.assert_matches_contract(envelope)
    assert first["data"]["purpose"] == "erp_mail" and first["data"]["notify"] is False
    assert first["data"]["request_key"].startswith("erp:mail:")
    assert opened(first) == {"text": "Текст", "html": "<b>HTML</b>", "links": []}
    assert second["data"]["to"] == ["a@example.com", "b@example.com", "c@example.com"]


def test_no_pair_secret_means_no_event_and_a_failed_log(settings, monkeypatch):
    import integration.bus

    settings.EMAIL_BACKEND = BUS_BACKEND
    monkeypatch.setattr(integration.bus, "pair_secrets", lambda publisher, subscriber: [])
    bus_support.reset()
    with pytest.raises(EmailDeliveryError, match="MAIL_PAIR_SECRET_MISSING"):
        send_templated_email("setup_password", CONTEXT, to=["alice@example.com"])
    assert mail_requests() == []
    assert EmailLog.objects.get().status == EmailLog.STATUS_FAILED


# ── вложение — по ссылке на объект хранилища ERP ──────────────────────────────────────────────────────


def test_attachment_goes_to_temp_storage_and_only_its_link_is_sealed(bus_mail, no_smtp, monkeypatch):
    import core.storage

    storage = _FakeTempStorage()
    monkeypatch.setattr(core.storage, "get_temp_storage", lambda: storage)
    pdf = b"%PDF-1.4 KP"
    send_templated_email(
        "setup_password", CONTEXT, to=["alice@example.com"], attachments=[("КП 42.pdf", pdf, "application/pdf")]
    )
    [envelope] = mail_requests()
    bus_support.assert_matches_contract(envelope)
    assert envelope["data"]["attachments"] == [
        {
            "filename": "КП 42.pdf",
            "content_type": "application/pdf",
            "size": len(pdf),
            "sha256": hashlib.sha256(pdf).hexdigest(),
        }
    ]
    [(key, stored)] = storage.saved.items()
    assert key.startswith("mail/") and key.endswith("КП_42.pdf") and stored == pdf
    [(method, params, expires)] = storage.calls
    assert (method, params, expires) == ("get_object", {"Bucket": "erp-temp", "Key": key}, 24 * 3600)
    [link] = opened(envelope)["links"]
    assert link["url"].startswith("http://rustfs:9000/erp-temp/mail/") and link["expires_at"].endswith("Z")
    assert "rustfs" not in str(envelope["data"]), "ссылка — только в шифртексте"


def test_attachment_without_s3_is_a_clear_error(bus_mail):
    with pytest.raises(EmailDeliveryError, match="MAIL_ATTACHMENT_STORAGE_UNAVAILABLE"):
        send_templated_email(
            "setup_password", CONTEXT, to=["alice@example.com"], attachments=[("a.pdf", b"x", "application/pdf")]
        )
    assert mail_requests() == []


# ── итог доставки от CRM ─────────────────────────────────────────────────────────────────────────────


def result(event_type, log=None, **extra):
    data = {
        "requester": "erp",
        "request_key": f"erp:email_log:{log.pk}" if log else "erp:mail:x",
        "purpose": "quote_sent",
        "email_log_id": 77,
        "attempts": 1,
    }
    if event_type == mail_bus.MAIL_SENT:
        data["sent_at"] = "2026-10-28T09:15:04Z"
    else:
        data.update(failed_at="2026-10-28T09:16:02Z", reason="rejected", detail="SMTP 550")
    data.update(extra)
    return data


def test_handlers_are_registered_for_both_results():
    assert default_registry.match(mail_bus.MAIL_SENT)
    assert default_registry.match(mail_bus.MAIL_FAILED)


def test_sent_and_failed_update_the_erp_mail_log_idempotently(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    ok = send_templated_email("setup_password", CONTEXT, to=["a@example.com"])
    bad = send_templated_email("setup_password", CONTEXT, to=["b@example.com"])

    for _ in range(2):
        mail_bus.apply_mail_result(mail_bus.MAIL_SENT, result(mail_bus.MAIL_SENT, ok))
        mail_bus.apply_mail_result(mail_bus.MAIL_FAILED, result(mail_bus.MAIL_FAILED, bad))
    ok.refresh_from_db()
    bad.refresh_from_db()
    assert (ok.status, ok.error) == (EmailLog.STATUS_SENT, "")
    assert (bad.status, bad.error) == (EmailLog.STATUS_FAILED, "rejected: SMTP 550")

    mail_bus.apply_mail_result(mail_bus.MAIL_FAILED, result(mail_bus.MAIL_FAILED, ok))
    ok.refresh_from_db()
    assert ok.status == EmailLog.STATUS_SENT, "«ошибка» после «отправлено» не применяется"


def test_results_of_other_requesters_are_ignored(settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    log = send_templated_email("setup_password", CONTEXT, to=["a@example.com"])
    mail_bus.apply_mail_result(mail_bus.MAIL_SENT, result(mail_bus.MAIL_SENT, log, requester="eds"))
    log.refresh_from_db()
    assert log.status == EmailLog.STATUS_QUEUED


def test_quote_mail_result_updates_send_report_and_quote_log():
    from crm.models import ActivityLog

    quote = add_quote(make_deal(make_company(), "QUOTE_SENT"), 1, "SENT", "1000")
    quote.send_report = {
        "requested": ["email", "cabinet"],
        "sent_via": ["cabinet", "email"],
        "skipped": [],
        "error": None,
    }
    quote.save(update_fields=["send_report"])
    ref = {"kind": "quote", "id": str(quote.pk)}

    for _ in range(2):
        mail_bus.apply_mail_result(mail_bus.MAIL_FAILED, result(mail_bus.MAIL_FAILED, ref=ref))
    quote.refresh_from_db()
    assert quote.send_report["sent_via"] == ["cabinet"]
    assert quote.send_report["skipped"] == [
        {"channel": "email", "reason": "EMAIL_DELIVERY_FAILED", "detail": "rejected"}
    ]
    logs = ActivityLog.objects.filter(entity_type="quote", entity_id=quote.pk, event_code="quote.email_failed")
    assert logs.count() == 1, "повтор итога второй записи в журнал КП не даёт"

    sent_quote = add_quote(
        make_deal(make_company(name="ООО Второй", crm_client_id=7002), "QUOTE_SENT"), 1, "SENT", "500"
    )
    sent_quote.send_report = {"requested": ["email"], "sent_via": ["email"], "skipped": [], "error": None}
    sent_quote.save(update_fields=["send_report"])
    mail_bus.apply_mail_result(
        mail_bus.MAIL_SENT, result(mail_bus.MAIL_SENT, ref={"kind": "quote", "id": str(sent_quote.pk)})
    )
    sent_quote.refresh_from_db()
    assert sent_quote.send_report["email_sent_at"] == "2026-10-28T09:15:04Z"
    assert ActivityLog.objects.filter(entity_id=sent_quote.pk, event_code="quote.email_sent").count() == 1

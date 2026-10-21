"""M3-ERP-06: `GET /health` отдаёт `externals[]` — внешние сервисы ERP — и выключатель `PUT /externals/{code}/switch`.

Каждый сервис — три исхода (работает, ошибка, нет данных); в ответе нет секретов; выключатель действительно
останавливает вызовы (курсы, ТН ВЭД, почта, модели, S3). Контракт — `Health.externals`, `ExternalSwitchState`.
"""

from __future__ import annotations

import datetime
import json

import pytest
from django.utils import timezone
from integration.services.externals import Facts, derive_status
from rest_framework.test import APIClient

from core import external_status as ext

pytestmark = pytest.mark.django_db

HEALTH = "/api/integration/v1/health"
TOKEN = "test-service-token"  # conftest._seam_secrets
SECRETS = ["hunter2", "sk-live-0123456789abcdef0123456789", "AKIAIOSFODNN7EXAMPLE", "smtp-user@example.com"]


@pytest.fixture
def client():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION=f"Bearer {TOKEN}")
    return api


@pytest.fixture(autouse=True)
def _no_anon_throttle(monkeypatch):
    from rest_framework.throttling import SimpleRateThrottle

    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "100000/minute")


def externals(client) -> dict[str, dict]:
    response = client.get(HEALTH)
    assert response.status_code == 200, response.content
    return {row["code"]: row for row in response.json()["externals"]}


def ago(**kwargs) -> datetime.datetime:
    return timezone.now() - datetime.timedelta(**kwargs)


# ── Общая форма ─────────────────────────────────────────────────────────────────────────────────────


def test_health_lists_all_six_services_in_contract_order(client):
    body = client.get(HEALTH).json()
    assert [row["code"] for row in body["externals"]] == [
        "cbu_rates",
        "customs_tariff",
        "mail",
        "litellm",
        "s3",
        "sentry",
    ]
    for row in body["externals"]:
        assert set(row) == {
            "code",
            "status",
            "enabled",
            "switchable",
            "last_success_at",
            "last_error_at",
            "last_error",
            "ok_24h",
            "errors_24h",
        }
        assert row["ok_24h"] == 0 and row["errors_24h"] == 0


def test_health_stays_cheap_no_external_calls_and_few_queries(client, monkeypatch, django_assert_max_num_queries):
    import smtplib
    import socket

    import httpx

    def forbidden(*args, **kwargs):
        raise AssertionError("/health не должен обращаться к внешним сервисам")

    monkeypatch.setattr(httpx, "get", forbidden)
    monkeypatch.setattr(httpx, "post", forbidden)
    monkeypatch.setattr(smtplib.SMTP, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    with django_assert_max_num_queries(30):
        assert client.get(HEALTH).status_code == 200


def test_health_without_externals_support_still_answers_when_building_fails(client, monkeypatch):
    """Сбой сборки одного сервиса — он `unknown`, остальные и сам /health живы."""

    def broken(now):
        raise RuntimeError("journal is unreadable")

    monkeypatch.setitem(__import__("integration.services.externals", fromlist=["_BUILDERS"])._BUILDERS, "mail", broken)
    rows = externals(client)
    assert rows["mail"]["status"] == "unknown"
    assert rows["cbu_rates"]["status"] == "unknown" and len(rows) == 6


# ── Курсы ЦБ ────────────────────────────────────────────────────────────────────────────────────────


def test_cbu_rates_unknown_ok_and_failure(client):
    assert externals(client)["cbu_rates"]["status"] == "unknown"

    ext.record_success("cbu_rates", at=ago(hours=3))
    row = externals(client)["cbu_rates"]
    assert (row["status"], row["ok_24h"], row["errors_24h"]) == ("ok", 1, 0)
    assert row["last_success_at"] and row["last_error_at"] is None and row["last_error"] is None

    ext.record_failure("cbu_rates", ConnectionError("cbu.uz unreachable"), at=ago(hours=1))
    row = externals(client)["cbu_rates"]
    assert row["status"] == "degraded", "последняя операция неудачна, но успех за сутки был"
    assert row["last_error"] == "ConnectionError: cbu.uz unreachable" and row["errors_24h"] == 1


def test_cbu_rates_fail_when_no_success_in_24h_and_stale_when_not_run(client):
    ext.record_success("cbu_rates", at=ago(hours=40))
    ext.record_failure("cbu_rates", TimeoutError("slow"), at=ago(hours=2))
    assert externals(client)["cbu_rates"]["status"] == "fail"

    from django.core.cache import cache

    cache.clear()
    ext.record_success("cbu_rates", at=ago(days=5))
    assert externals(client)["cbu_rates"]["status"] == "degraded", "плановая задача давно не выполнялась"


def test_cbu_rates_last_success_falls_back_to_the_loaded_rows_when_cache_is_empty(client):
    from core.models import Currency, ExchangeRate

    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "$"})[0]
    ExchangeRate.objects.create(currency=usd, rate_to_uzs=12000, rate_date=timezone.localdate(), source="CBU")
    row = externals(client)["cbu_rates"]
    assert row["status"] == "ok" and row["last_success_at"] is not None


def test_refresh_exchange_rates_task_reports_its_outcome(client, monkeypatch):
    from master_data.tasks import refresh_exchange_rates

    monkeypatch.setattr("finance.services.fx.fetch_cbu_rates", lambda: 3)
    assert refresh_exchange_rates.apply().get() == 3
    row = externals(client)["cbu_rates"]
    assert (row["status"], row["ok_24h"]) == ("ok", 1)

    def down():
        raise ConnectionError("cbu down")

    monkeypatch.setattr("finance.services.fx.fetch_cbu_rates", down)
    assert refresh_exchange_rates.apply().failed()
    row = externals(client)["cbu_rates"]
    assert row["errors_24h"] >= 1 and row["last_error"].startswith("ConnectionError")


# ── ТН ВЭД / тариф ──────────────────────────────────────────────────────────────────────────────────


def test_customs_tariff_task_reports_its_outcome(client, monkeypatch):
    from master_data.tasks import refresh_tnved_codes

    assert externals(client)["customs_tariff"]["status"] == "unknown"
    monkeypatch.setattr("master_data.tnved.sync_tnved_codes", lambda: {"fetched": 13000})
    assert refresh_tnved_codes.apply().get() == {"fetched": 13000}
    assert externals(client)["customs_tariff"]["status"] == "ok"

    def truncated():
        raise ValueError("ТН ВЭД: источник вернул 5 кодов при ожидаемых ≥10000")

    monkeypatch.setattr("master_data.tnved.sync_tnved_codes", truncated)
    assert refresh_tnved_codes.apply().failed()
    row = externals(client)["customs_tariff"]
    assert row["status"] == "degraded" and row["last_error"].startswith("ValueError: ТН ВЭД")


def test_customs_tariff_stale_after_two_weeks(client):
    ext.record_success("customs_tariff", at=ago(days=20))
    assert externals(client)["customs_tariff"]["status"] == "degraded"


# ── Почта ───────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def smtp_mail(settings):
    settings.EMAIL_CHANNELS = {"transactional": {"backend": "django.core.mail.backends.smtp.EmailBackend"}}


def email_log(status, error="", created=None, template="t"):
    from core.models import EmailLog

    row = EmailLog.objects.create(
        template=template,
        channel="transactional",
        subject="s",
        from_email="a@b.c",
        to_emails=["x@y.z"],
        status=status,
        error=error,
    )
    if created:
        EmailLog.objects.filter(pk=row.pk).update(created_at=created)
    return row


def test_mail_is_disabled_without_a_real_relay(client):
    assert externals(client)["mail"]["status"] == "disabled", "locmem/console — реального релея нет"


def test_mail_unknown_ok_degraded_fail(client, smtp_mail):
    assert externals(client)["mail"]["status"] == "unknown"

    email_log("SENT", created=ago(hours=5))
    email_log("SENT", created=ago(hours=4))
    row = externals(client)["mail"]
    assert (row["status"], row["ok_24h"], row["errors_24h"]) == ("ok", 2, 0)

    email_log("FAILED", "SMTPServerDisconnected: connection unexpectedly closed", created=ago(hours=1))
    row = externals(client)["mail"]
    assert row["status"] == "degraded" and row["errors_24h"] == 1
    assert row["last_error"] == "SMTPServerDisconnected: connection unexpectedly closed"

    from core.models import EmailLog

    EmailLog.objects.filter(status="SENT").update(created_at=ago(hours=30))
    assert externals(client)["mail"]["status"] == "fail", "за 24 ч успешных нет, последнее письмо не ушло"


def test_mail_ignores_letters_held_back_by_the_switch(client, smtp_mail):
    email_log("SENT", created=ago(hours=2))
    email_log("FAILED", f"{ext.SWITCHED_OFF_MARK}: отправка выключена из CRM", created=ago(hours=1))
    row = externals(client)["mail"]
    assert (row["status"], row["errors_24h"], row["last_error_at"]) == ("ok", 0, None)


def test_send_templated_email_does_not_reach_smtp_when_switched_off(client, smtp_mail, monkeypatch, settings):
    from core.models import EmailLog
    from notifications.emails import EmailDeliveryError, send_templated_email

    settings.EMAIL_CHANNELS = {
        "transactional": {
            "backend": "django.core.mail.backends.locmem.EmailBackend",
            "host": "h",
            "port": 25,
            "username": "",
            "password": "",
            "use_tls": False,
            "from_email": "noreply@example.com",
        }
    }
    sent = []
    monkeypatch.setattr(
        "django.core.mail.EmailMultiAlternatives.send", lambda self, fail_silently=False: sent.append(self) or 1
    )
    ext.set_enabled("mail", False, reason="утечка")

    with pytest.raises(EmailDeliveryError):
        send_templated_email("setup_password", {"first_name": "А", "setup_url": "https://x"}, to=["a@example.com"])
    log = send_templated_email(
        "setup_password", {"first_name": "А", "setup_url": "https://x"}, to=["a@example.com"], fail_silently=True
    )
    assert sent == [], "в SMTP ничего не ушло"
    assert log.status == EmailLog.STATUS_FAILED and log.error.startswith(ext.SWITCHED_OFF_MARK)

    ext.set_enabled("mail", True)
    send_templated_email("setup_password", {"first_name": "А", "setup_url": "https://x"}, to=["a@example.com"])
    assert len(sent) == 1


# ── LiteLLM ─────────────────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def ai_on(settings):
    settings.AI_IMPORT_ENABLED = True
    settings.LITELLM_BASE_URL = "http://litellm.test"
    settings.LITELLM_API_KEY = "sk-erp-test"


def ai_call(status, error_code="", created=None):
    from ai.models import AICall

    row = AICall.objects.create(
        session_id="m3-06",
        feature="match",
        model_alias="match-model",
        prompt_name="p",
        prompt_version="v",
        status=status,
        error_code=error_code,
    )
    if created:
        AICall.objects.filter(pk=row.pk).update(created_at=created)
    return row


def test_litellm_is_disabled_when_ai_is_off(client):
    assert externals(client)["litellm"]["status"] == "disabled"


def test_litellm_unknown_ok_degraded_fail(client, ai_on):
    assert externals(client)["litellm"]["status"] == "unknown"

    ai_call("ok", created=ago(hours=3))
    ai_call("invalid_json", "AI_BAD_RESPONSE", created=ago(hours=2))  # шлюз ответил — качество модели не сбой сервиса
    ai_call("budget", "AI_BUDGET_EXCEEDED", created=ago(hours=1))  # бюджет — не сбой шлюза
    row = externals(client)["litellm"]
    assert (row["status"], row["ok_24h"], row["errors_24h"]) == ("ok", 2, 0)

    ai_call("error", "AI_GATEWAY_UNAVAILABLE", created=ago(minutes=5))
    row = externals(client)["litellm"]
    assert row["status"] == "degraded" and row["last_error"] == "AI_GATEWAY_UNAVAILABLE" and row["errors_24h"] == 1

    from ai.models import AICall

    AICall.objects.filter(status__in=["ok", "invalid_json"]).update(created_at=ago(hours=40))
    assert externals(client)["litellm"]["status"] == "fail"


def test_call_json_does_not_call_the_gateway_when_switched_off(ai_on, fake_gateway):
    from ai.models import AICall
    from ai.services.gateway import JsonCall, call_json
    from ai.services.prompts import load_prompt

    ext.set_enabled("litellm", False)
    prompt = load_prompt("match")
    result = call_json(JsonCall("match", prompt, "sys", [], {"type": "object"}, 100))
    assert result.status == "disabled" and result.error_code == "AI_GATEWAY_UNAVAILABLE"
    assert not fake_gateway.calls and AICall.objects.count() == 0


# ── S3 ──────────────────────────────────────────────────────────────────────────────────────────────


def test_s3_disabled_without_endpoint_then_unknown_ok_fail(client, settings):
    assert externals(client)["s3"]["status"] == "disabled"
    settings.MINIO_ENDPOINT = "http://minio:9000"
    assert externals(client)["s3"]["status"] == "unknown"

    ext.record_success("s3", at=ago(minutes=30))
    assert externals(client)["s3"]["status"] == "ok"
    ext.record_failure(
        "s3", ConnectionError("Could not connect to the endpoint URL: http://minio:9000/erp-private/x.pdf")
    )
    row = externals(client)["s3"]
    assert row["status"] == "degraded" and "x.pdf" not in row["last_error"]
    assert row["last_error"].startswith("ConnectionError: Could not connect to the endpoint URL: http://minio:9000")


class _FakeS3:
    """Родитель вместо S3Boto3Storage: операции сети подменены."""

    def __init__(self, fail=None):
        self.fail, self.calls = fail, []

    def _save(self, name, content):
        self.calls.append("save")
        if self.fail:
            raise self.fail
        return name

    def _open(self, name, mode="rb"):
        self.calls.append("open")
        return b"data"

    def delete(self, name):
        self.calls.append("delete")


def test_s3_storage_reports_outcomes_and_honours_the_switch():
    from core.storage import TrackedStorageMixin

    class Storage(TrackedStorageMixin, _FakeS3):
        pass

    storage = Storage()
    assert storage._save("a.pdf", b"x") == "a.pdf" and storage._open("a.pdf") == b"data"
    storage.delete("a.pdf")
    assert ext.counts("s3") == (3, 0)

    failing = Storage(fail=OSError("endpoint down"))
    with pytest.raises(OSError):
        failing._save("b.pdf", b"x")
    assert ext.counts("s3") == (3, 1)

    class MissingFake(_FakeS3):
        def _open(self, name, mode="rb"):
            raise FileNotFoundError(name)

    class MissingStorage(TrackedStorageMixin, MissingFake):
        pass

    with pytest.raises(FileNotFoundError):
        MissingStorage()._open("gone.pdf")
    assert ext.counts("s3") == (4, 1), "404 на несуществующий файл — не сбой хранилища"

    ext.set_enabled("s3", False)
    with pytest.raises(ext.ExternalSwitchedOff):
        storage._save("c.pdf", b"x")
    assert storage.calls.count("save") == 1, "выключенное хранилище не вызывается"
    assert ext.counts("s3") == (4, 1)


# ── Sentry ──────────────────────────────────────────────────────────────────────────────────────────


def test_sentry_is_disabled_without_dsn_and_ok_with_it_without_leaking_the_dsn(client, settings):
    row = externals(client)["sentry"]
    assert (row["status"], row["switchable"], row["enabled"]) == ("disabled", False, True)
    settings.SENTRY_DSN = "https://publickey@o123.ingest.sentry.io/456"
    response = client.get(HEALTH)
    assert {r["code"]: r for r in response.json()["externals"]}["sentry"]["status"] == "ok"
    assert "publickey" not in response.content.decode()


# ── Секреты ─────────────────────────────────────────────────────────────────────────────────────────


def test_no_secret_reaches_the_response(client, smtp_mail, ai_on, settings):
    settings.MINIO_ENDPOINT = "http://minio:9000"
    settings.SENTRY_DSN = "https://publickey@o123.ingest.sentry.io/456"
    ext.record_failure("cbu_rates", RuntimeError("https://admin:hunter2@cbu.uz/json?token=hunter2"))
    ext.record_failure("customs_tariff", RuntimeError("Authorization: Bearer sk-live-0123456789abcdef0123456789"))
    ext.record_failure("s3", RuntimeError("AccessDenied for key AKIAIOSFODNN7EXAMPLE"))
    email_log("FAILED", "SMTPAuthenticationError: (535, b'smtp-user@example.com password=hunter2')")
    ai_call("error", "AI_GATEWAY_ERROR")
    text = client.get(HEALTH).content.decode()
    for secret in SECRETS + ["publickey", "sk-erp-test", "minio:9000/erp"]:
        assert secret not in text, secret
    rows = {r["code"]: r for r in json.loads(text)["externals"]}
    assert all(len(r["last_error"] or "") <= 200 for r in rows.values())


# ── Выключатель: PUT /externals/{code}/switch ───────────────────────────────────────────────────────


def put(client, code, body):
    return client.put(f"/api/integration/v1/externals/{code}/switch", data=body, format="json")


def test_switch_off_and_on_is_idempotent_and_visible_in_health(client):
    response = put(client, "cbu_rates", {"enabled": False, "reason": "ЦБ меняет формат"})
    assert response.status_code == 200
    body = response.json()
    assert (body["code"], body["enabled"]) == ("cbu_rates", False) and body["changed_at"]
    assert put(client, "cbu_rates", {"enabled": False}).json()["enabled"] is False

    row = externals(client)["cbu_rates"]
    assert (row["enabled"], row["status"]) == (False, "disabled")

    assert put(client, "cbu_rates", {"enabled": True}).json()["enabled"] is True
    assert externals(client)["cbu_rates"]["enabled"] is True


@pytest.mark.parametrize("code", ["cbu_rates", "customs_tariff", "mail", "litellm", "s3"])
def test_every_switchable_service_accepts_the_switch(client, code):
    assert put(client, code, {"enabled": False}).status_code == 200
    assert externals(client)[code]["enabled"] is False
    assert ext.is_enabled(code) is False


def test_switch_errors(client):
    assert put(client, "telegram", {"enabled": False}).json() == {"detail": "NOT_FOUND"}
    assert put(client, "telegram", {"enabled": False}).status_code == 404
    sentry = put(client, "sentry", {"enabled": False})
    assert (sentry.status_code, sentry.json()) == (409, {"detail": "NOT_SWITCHABLE"})
    for bad in ({}, {"enabled": "maybe"}, {"enabled": None}, {"enabled": False, "reason": "x" * 201}):
        response = put(client, "mail", bad)
        assert (response.status_code, response.json()) == (422, {"detail": "VALIDATION_ERROR"}), bad
    assert (
        APIClient().put("/api/integration/v1/externals/mail/switch", {"enabled": False}, format="json").status_code
        == 401
    )


def test_switched_off_cbu_and_tnved_tasks_skip_the_call(monkeypatch):
    from master_data.tasks import refresh_exchange_rates, refresh_tnved_codes

    def must_not_run(*args, **kwargs):
        raise AssertionError("сервис выключен — вызова быть не должно")

    monkeypatch.setattr("finance.services.fx.fetch_cbu_rates", must_not_run)
    monkeypatch.setattr("master_data.tnved.sync_tnved_codes", must_not_run)
    ext.set_enabled("cbu_rates", False)
    ext.set_enabled("customs_tariff", False)
    assert refresh_exchange_rates.apply().get() == 0
    assert refresh_tnved_codes.apply().get() == {"skipped": "switched_off"}
    assert ext.counts("cbu_rates") == (0, 0) and ext.counts("customs_tariff") == (0, 0)


# ── Правила статуса ─────────────────────────────────────────────────────────────────────────────────


def test_status_rules():
    now = timezone.now()
    h = datetime.timedelta
    on = {"enabled": True, "now": now}
    assert derive_status(Facts(configured=False), **on) == "disabled"
    assert derive_status(Facts(configured=True), enabled=False, now=now) == "disabled"
    assert derive_status(Facts(configured=True), **on) == "unknown"
    assert derive_status(Facts(True, last_success_at=now - h(hours=1), ok_24h=1), **on) == "ok"
    # ошибка раньше успеха — сервис восстановился
    assert derive_status(Facts(True, now - h(hours=1), now - h(hours=2), "x", 1, 1), **on) == "ok"
    assert derive_status(Facts(True, now - h(hours=2), now - h(hours=1), "x", 5, 1), **on) == "degraded"
    assert derive_status(Facts(True, None, now - h(hours=1), "x", 0, 1), **on) == "fail"
    assert derive_status(Facts(True, now - h(days=4), None, None, 0, 0, h(days=3)), **on) == "degraded"
    assert derive_status(Facts(True, now - h(days=2), None, None, 0, 0, h(days=3)), **on) == "ok"

"""Admin · Внешние интеграции (W13-A1, контракт BFF 0.7.0): прокси к CRM, `/admin/integrations/*`.

CRM — на respx (`integrations_support`), ответы BFF проверяются по схемам platform-bff.yaml.
Проверяется то, что делает BFF: раздел каталога (чтение — `admin: read`, всё изменяющее и каждая
проба — `admin: full`, 403 до CRM), токен сотрудника в CRM, тело запроса к CRM, то, что секреты
уходят только в CRM и не возвращаются, и перевод ошибок CRM в единый формат `Error`. Решения
(пароль, шифрование, состояние сервисов) — за CRM.
"""

from typing import Any

import httpx
import pytest

from app.clients.base import PROBE_TIMEOUT_SECONDS
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.integrations_support import (
    CrmIntegrationsFake,
    fresh_secret,
    service,
    services_out,
)

BASE = "/api/v1/admin/integrations"
PASSWORD = "adm-" + fresh_secret("pw", 6)  # пароль администратора, придуманный на этот прогон


@pytest.fixture
def crm(be: Backends) -> CrmIntegrationsFake:
    return CrmIntegrationsFake(be)


# (метод, путь BFF, шаблон пути контракта, тело) — каждый эндпоинт экрана
READS: tuple[tuple[str, str], ...] = (
    (f"{BASE}", "/admin/integrations"),
    (f"{BASE}/erp", "/admin/integrations/erp"),
    (f"{BASE}/telegram", "/admin/integrations/telegram"),
    (f"{BASE}/telegram/channels", "/admin/integrations/telegram/channels"),
    (f"{BASE}/telegram/profile", "/admin/integrations/telegram/profile"),
    (f"{BASE}/smtp", "/admin/integrations/smtp"),
    (f"{BASE}/smtp/log", "/admin/integrations/smtp/log"),
    (f"{BASE}/services", "/admin/integrations/services"),
    (f"{BASE}/services/telegram", "/admin/integrations/services/{key}"),
    (f"{BASE}/models", "/admin/integrations/models"),
    (f"{BASE}/spend", "/admin/integrations/spend"),
    (f"{BASE}/ai-spend", "/admin/integrations/ai-spend"),
    (f"{BASE}/backups", "/admin/integrations/backups"),
    (f"{BASE}/system", "/admin/integrations/system"),
)
TOKEN = "t" * 24 + "-fake-bot-token"
WRITES: tuple[tuple[str, str, str, dict[str, Any] | None], ...] = (
    ("POST", f"{BASE}/erp/check", "/admin/integrations/erp/check", None),
    (
        "POST",
        f"{BASE}/erp/pair",
        "/admin/integrations/erp/pair",
        {"base_url": "http://erp.test", "code": "123456", "password": PASSWORD},
    ),
    ("POST", f"{BASE}/erp/rotate", "/admin/integrations/erp/rotate", {"password": PASSWORD}),
    (
        "PUT",
        f"{BASE}/telegram/token",
        "/admin/integrations/telegram/token",
        {"token": TOKEN, "password": PASSWORD},
    ),
    (
        "POST",
        f"{BASE}/telegram/channels/-1001/connect",
        "/admin/integrations/telegram/channels/{chat_id}/connect",
        None,
    ),
    ("POST", f"{BASE}/telegram/channel/test", "/admin/integrations/telegram/channel/test", None),
    (
        "PUT",
        f"{BASE}/telegram/profile",
        "/admin/integrations/telegram/profile",
        {
            "name": {"ru": "Бот", "uz": "Bot", "en": "Bot"},
            "short_description": {"ru": "К", "uz": "Q", "en": "S"},
            "description": {"ru": "О", "uz": "T", "en": "D"},
        },
    ),
    (
        "PUT",
        f"{BASE}/smtp",
        "/admin/integrations/smtp",
        {"host": "smtp.demo.example", "password": PASSWORD},
    ),
    ("POST", f"{BASE}/smtp/check", "/admin/integrations/smtp/check", None),
    ("POST", f"{BASE}/smtp/test-send", "/admin/integrations/smtp/test-send", None),
    ("POST", f"{BASE}/services/mail/check", "/admin/integrations/services/{key}/check", None),
    (
        "POST",
        f"{BASE}/services/mail/disable",
        "/admin/integrations/services/{key}/disable",
        {"password": PASSWORD},
    ),
    (
        "POST",
        f"{BASE}/services/mail/enable",
        "/admin/integrations/services/{key}/enable",
        {"password": PASSWORD},
    ),
    (
        "PUT",
        f"{BASE}/models/dialog-model",
        "/admin/integrations/models/{alias}",
        {"provider": "openai", "model": "gpt-demo", "password": PASSWORD},
    ),
    (
        "POST",
        f"{BASE}/models/dialog-model/reset",
        "/admin/integrations/models/{alias}/reset",
        {"password": PASSWORD},
    ),
    ("POST", f"{BASE}/models/dialog-model/test", "/admin/integrations/models/{alias}/test", None),
    ("POST", f"{BASE}/backups", "/admin/integrations/backups", None),
)


# --- права: раздел каталога, до CRM -------------------------------------------------------------


@pytest.mark.parametrize("role", ["MANAGER", "SUPPLY", "ENGINEER", "ACCOUNTANT"])
async def test_role_without_admin_gets_403_on_every_endpoint(
    web: Web, crm: CrmIntegrationsFake, role: str
) -> None:
    """Нет раздела `admin` — 403 в BFF на каждом эндпоинте, CRM не вызывается."""
    await web.login([role])
    before = crm.count

    for url, _ in READS:
        response = await web.client.get(url)
        assert response.status_code == 403, url
        assert response.json()["details"] == {"resource": "admin", "need": "read"}
    for method, url, _, body in WRITES:
        response = await web.send(method, url, json=body)  # type: ignore[arg-type]
        assert response.status_code == 403, (method, url)
        assert response.json()["details"] == {"resource": "admin", "need": "full"}
    assert crm.count == before


async def test_director_reads_but_every_change_is_403(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    """Директор (`admin: read`) читает все карточки; изменения и пробы — 403 до CRM."""
    await web.login(["DIRECTOR"])

    for url, template in READS:
        response = await web.client.get(url)
        assert response.status_code == 200, url
        check(response, template, "get")
    reads_done = crm.count
    for method, url, _, body in WRITES:
        response = await web.send(method, url, json=body)  # type: ignore[arg-type]
        assert response.status_code == 403, (method, url)
        assert response.json()["details"] == {"resource": "admin", "need": "full"}
    assert crm.count == reads_done


async def test_session_and_csrf_are_required(web: Web, crm: CrmIntegrationsFake) -> None:
    anonymous = await web.client.get(f"{BASE}/erp")
    assert anonymous.status_code == 401
    assert anonymous.json()["code"] == "SESSION_EXPIRED"

    await web.login(["ADMIN"])
    no_csrf = await web.send("POST", f"{BASE}/erp/rotate", json={"password": PASSWORD}, csrf="x")
    assert no_csrf.status_code == 403
    assert no_csrf.json()["code"] == "CSRF_FAILED"
    assert crm.requests("POST", "integrations/erp/rotate") == []


# --- каждый эндпоинт: админ, тело к CRM, ответ по контракту -------------------------------------


@pytest.mark.parametrize(("url", "template"), READS)
async def test_admin_reads_every_endpoint_with_staff_token(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker, url: str, template: str
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get(url)

    assert response.status_code == 200
    check(response, template, "get")
    assert crm.calls, "CRM не вызывали"
    for call in crm.calls:
        assert call.headers["authorization"].startswith("Bearer crm-access-")


@pytest.mark.parametrize(("method", "url", "template", "body"), WRITES)
async def test_admin_runs_every_action(
    web: Web,
    crm: CrmIntegrationsFake,
    check: ContractChecker,
    method: str,
    url: str,
    template: str,
    body: dict[str, Any] | None,
) -> None:
    await web.login(["ADMIN"])

    response = await web.send(method, url, json=body)  # type: ignore[arg-type]

    expected = 202 if url.endswith("/backups") else 200
    assert response.status_code == expected, response.text
    check(response, template, method.lower())
    sent = crm.calls[-1]
    assert sent.method == method
    assert sent.headers["authorization"].startswith("Bearer crm-access-")


async def test_probes_wait_longer_than_a_normal_call(web: Web, crm: CrmIntegrationsFake) -> None:
    """Проба ждёт CRM до 30 с (SMTP у самой CRM — 10 с), обычное чтение — таймаут клиента."""
    await web.login(["ADMIN"])

    await web.client.get(f"{BASE}/erp")
    await web.send("POST", f"{BASE}/smtp/check")

    read, probe = crm.last("GET", "integrations/erp"), crm.last("POST", "integrations/smtp/check")
    assert read.extensions["timeout"]["read"] == 5.0
    assert probe.extensions["timeout"]["read"] == PROBE_TIMEOUT_SECONDS


# --- ERP ----------------------------------------------------------------------------------------


async def test_erp_connector_shows_masks_only(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get(f"{BASE}/erp")

    body = response.json()
    assert body["token_configured"] is True
    assert body["token_last4"] == "9f3c"
    assert body["webhook_secret_last4"] == "77de"
    # поля CRM, которых нет в контракте BFF, не пробрасываются
    assert "inbound_token_last4" not in body
    assert "bootstrap_available" not in body


async def test_erp_pair_passes_password_and_code_only_to_crm(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    code = "428" + fresh_secret("c", 4)

    response = await web.send(
        "POST",
        f"{BASE}/erp/pair",
        json={"base_url": " http://erp.test ", "code": code, "password": PASSWORD},
    )

    assert response.status_code == 200
    assert crm.body("POST", "integrations/erp/pair") == {
        "base_url": "http://erp.test",
        "code": code,
        "password": PASSWORD,
    }
    assert PASSWORD not in response.text
    assert code not in response.text
    assert response.json()["check"]["status"] == "ok"
    assert response.json()["check_error"] is None


async def test_erp_rotate_returns_rotation_pending_without_secrets(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/erp/rotate", json={"password": PASSWORD})

    assert response.json()["status"]["rotation_pending"] is True
    assert crm.body("POST", "integrations/erp/rotate") == {"password": PASSWORD}
    assert PASSWORD not in response.text


async def test_erp_check_rate_limited_is_a_status_not_an_error(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    crm.answer(
        "POST",
        "integrations/erp/check",
        200,
        {
            "status": "rate_limited",
            "checked_at": "2026-10-26T09:00:00Z",
            "latency_ms": None,
            "version": None,
            "migrations_applied": None,
            "queue_alive": None,
            "retry_after_s": 30,
        },
    )
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/erp/check")

    assert response.status_code == 200
    assert response.json()["status"] == "rate_limited"
    assert response.json()["retry_after_s"] == 30


# --- Telegram: токен — только вход --------------------------------------------------------------


async def test_telegram_token_goes_to_crm_and_never_comes_back(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    token = "123456:" + fresh_secret("bot", 24)

    response = await web.send(
        "PUT", f"{BASE}/telegram/token", json={"token": token, "password": PASSWORD}
    )

    assert response.status_code == 200
    check(response, "/admin/integrations/telegram/token", "put")
    assert crm.body("PUT", "integrations/telegram/token") == {"token": token, "password": PASSWORD}
    assert token not in response.text
    assert PASSWORD not in response.text
    assert response.json()["last4"] == "Zz9y"
    assert response.json()["configured"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"token": "short", "password": PASSWORD},
        {"token": "x" * 24},
        {"token": "x" * 24, "password": PASSWORD, "extra": 1},
    ],
)
async def test_telegram_token_body_is_validated_before_crm(
    web: Web, crm: CrmIntegrationsFake, payload: dict[str, Any]
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("PUT", f"{BASE}/telegram/token", json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert crm.requests("PUT", "integrations/telegram/token") == []


async def test_validation_error_does_not_echo_secret_values(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    await web.login(["ADMIN"])

    response = await web.send(
        "PUT", f"{BASE}/telegram/token", json={"token": "tiny-secret-value", "password": PASSWORD}
    )

    assert response.status_code == 422
    assert "tiny-secret-value" not in response.text
    assert PASSWORD not in response.text


async def test_telegram_channel_connect_and_test(web: Web, crm: CrmIntegrationsFake) -> None:
    await web.login(["ADMIN"])

    listed = await web.client.get(f"{BASE}/telegram/channels")
    connected = await web.send("POST", f"{BASE}/telegram/channels/-1001/connect")
    tested = await web.send("POST", f"{BASE}/telegram/channel/test")

    assert listed.json()["items"][0] == {
        "chat_id": -1001,
        "chat_type": "supergroup",
        "detected_at": "2026-10-26T08:55:00Z",
        "title": "Команда (демо)",
    }
    assert connected.json() == {"id": None, "ok": True}
    assert tested.json() == {"id": None, "ok": True}
    assert crm.requests("POST", "integrations/telegram/channels/-1001/connect")


async def test_bot_profile_roundtrip(web: Web, crm: CrmIntegrationsFake) -> None:
    await web.login(["ADMIN"])
    profile = {
        "name": {"ru": "Новый", "uz": "Yangi", "en": "New"},
        "short_description": {"ru": "К", "uz": "Q", "en": "S"},
        "description": {"ru": "О", "uz": "T", "en": "D"},
    }

    read = await web.client.get(f"{BASE}/telegram/profile")
    saved = await web.send("PUT", f"{BASE}/telegram/profile", json=profile)

    assert read.json()["profile"]["name"]["uz"] == "Demo bot"
    assert read.json()["published"]["ok"] is True
    assert saved.status_code == 200
    assert crm.body("PUT", "integrations/telegram/profile") == profile


# --- почта --------------------------------------------------------------------------------------


async def test_smtp_save_sends_both_passwords_to_crm_only(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    smtp_password = fresh_secret("smtp", 12)

    response = await web.send(
        "PUT",
        f"{BASE}/smtp",
        json={
            "host": " smtp.demo.example ",
            "port": 465,
            "security": "ssl",
            "from_email": "noreply@demo.example",
            "from_name": "RailTech (демо)",
            "username": "mailer",
            "smtp_password": smtp_password,
            "password": PASSWORD,
        },
    )

    assert response.status_code == 200
    check(response, "/admin/integrations/smtp", "put")
    assert crm.body("PUT", "integrations/smtp") == {
        "host": "smtp.demo.example",
        "port": 465,
        "security": "ssl",
        "from_email": "noreply@demo.example",
        "from_name": "RailTech (демо)",
        "username": "mailer",
        "smtp_password": smtp_password,
        "password": PASSWORD,
    }
    assert smtp_password not in response.text
    assert PASSWORD not in response.text
    assert response.json()["password_last4"] == "k3Zp"
    assert "settings_source" not in response.json()


async def test_smtp_keeps_previous_password_when_not_sent(
    web: Web, crm: CrmIntegrationsFake
) -> None:
    await web.login(["ADMIN"])

    await web.send("PUT", f"{BASE}/smtp", json={"host": "smtp.demo.example", "password": PASSWORD})

    sent = crm.body("PUT", "integrations/smtp")
    assert sent["smtp_password"] is None
    assert sent["username"] is None
    assert sent["port"] == 587
    assert sent["security"] == "starttls"


async def test_mail_log_filters_and_hides_internal_fields(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get(f"{BASE}/smtp/log", params={"status": "failed", "limit": 5})

    assert response.status_code == 200
    check(response, "/admin/integrations/smtp/log", "get")
    assert dict(crm.last("GET", "integrations/smtp/log").url.params) == {
        "status": "failed",
        "limit": "5",
    }
    row = response.json()["items"][0]
    assert set(row) == {
        "attempts",
        "created_at",
        "error",
        "id",
        "sent_at",
        "status",
        "subject",
        "template",
        "to_email",
    }
    bad = await web.client.get(f"{BASE}/smtp/log", params={"status": "bounced"})
    assert bad.status_code == 422


async def test_smtp_test_send_is_queued(web: Web, crm: CrmIntegrationsFake) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/smtp/test-send")

    assert response.json() == {
        "email_log_id": 31,
        "status": "queued",
        "to_email": "admin@demo.example",
    }


# --- внешние сервисы ----------------------------------------------------------------------------


async def test_services_registry_maps_fix_path_to_card_and_hides_crm_paths(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    crm.answer(
        "GET",
        "admin/external-services",
        200,
        services_out(
            [
                service("telegram", "fail"),
                service("mail", "ok", fix_path="/integrations?tab=mail"),
                service("clients_view", "warn", fix_path="/clients"),
            ]
        ),
    )
    await web.login(["ADMIN"])

    response = await web.client.get(f"{BASE}/services")

    check(response, "/admin/integrations/services", "get")
    items = {s["key"]: s for s in response.json()["items"]}
    assert items["telegram"]["fix_card"] == "telegram"
    assert items["mail"]["fix_card"] == "mail"
    assert items["clients_view"]["fix_card"] is None
    assert "fix_path" not in response.text
    assert "metrics" not in response.text
    assert response.json()["summary"]["fail"] == 1


async def test_service_detail_and_check(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    detail = await web.client.get(f"{BASE}/services/telegram")
    checked = await web.send("POST", f"{BASE}/services/telegram/check")

    for response in (detail, checked):
        assert response.status_code == 200
        assert response.json()["service"]["key"] == "telegram"
        assert response.json()["incidents"][0]["duration_s"] == 300
    bad = await web.client.get(f"{BASE}/services/Bad%20Key")
    assert bad.status_code == 422


async def test_service_switch_passes_password_and_reason(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    off = await web.send(
        "POST", f"{BASE}/services/mail/disable", json={"password": PASSWORD, "reason": "ремонт"}
    )
    on = await web.send("POST", f"{BASE}/services/mail/enable", json={"password": PASSWORD})

    assert off.json()["switch"]["disabled"] is True
    assert on.json()["switch"]["disabled"] is False
    assert crm.body("POST", "admin/external-services/mail/disable") == {
        "password": PASSWORD,
        "reason": "ремонт",
    }
    assert crm.body("POST", "admin/external-services/mail/enable") == {"password": PASSWORD}
    assert PASSWORD not in off.text + on.text


async def test_service_not_switchable_is_a_named_conflict(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    crm.error(
        "POST", "admin/external-services/s3/disable", 409, "conflict", "service_not_switchable"
    )
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/services/s3/disable", json={"password": PASSWORD})

    assert response.status_code == 409
    check(response, "/admin/integrations/services/{key}/disable", "post")
    assert response.json()["code"] == "SERVICE_NOT_SWITCHABLE"
    assert response.json()["source"] == "crm"
    assert response.json()["details"]["reason"] == "service_not_switchable"


# --- модели ИИ, расходы -------------------------------------------------------------------------


async def test_model_change_sends_key_to_crm_and_reports_only_its_source(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    api_key = "sk-" + fresh_secret("key", 20)

    response = await web.send(
        "PUT",
        f"{BASE}/models/embed-model",
        json={
            "provider": "openai",
            "model": " gpt-demo ",
            "api_key": api_key,
            "password": PASSWORD,
        },
    )

    assert response.status_code == 200
    check(response, "/admin/integrations/models/{alias}", "put")
    assert crm.body("PUT", "models/embed-model") == {
        "provider": "openai",
        "model": "gpt-demo",
        "api_key": api_key,
        "api_base": None,
        "password": PASSWORD,
    }
    assert api_key not in response.text
    assert PASSWORD not in response.text
    assert response.json()["key_source"] == "crm"
    assert response.json()["reindex_required"] is True


@pytest.mark.parametrize(
    "payload",
    [
        {"provider": "yandex", "model": "m", "password": PASSWORD},
        {"provider": "openai", "model": "", "password": PASSWORD},
        {"provider": "openai", "model": "m", "api_key": "short", "password": PASSWORD},
        {"provider": "openai", "model": "m"},
    ],
)
async def test_model_change_body_is_validated(
    web: Web, crm: CrmIntegrationsFake, payload: dict[str, Any]
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("PUT", f"{BASE}/models/dialog-model", json=payload)

    assert response.status_code == 422
    assert crm.requests("PUT", "models/dialog-model") == []


async def test_model_reset_and_test(web: Web, crm: CrmIntegrationsFake) -> None:
    await web.login(["ADMIN"])

    reset = await web.send("POST", f"{BASE}/models/dialog-model/reset", json={"password": PASSWORD})
    tested = await web.send("POST", f"{BASE}/models/dialog-model/test")
    listed = await web.client.get(f"{BASE}/models")

    assert reset.json()["key_source"] == "env"
    assert tested.json() == {
        "alias": "dialog-model",
        "cost_usd": 0.0002,
        "detail": None,
        "latency_ms": 900,
        "ok": True,
    }
    assert [m["alias"] for m in listed.json()["items"]] == ["dialog-model", "embed-model"]
    assert crm.body("POST", "models/dialog-model/reset") == {"password": PASSWORD}


async def test_spend_reports_pass_period_and_hide_lead_names(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    bot = await web.client.get(f"{BASE}/spend", params={"days": 14})
    ensemble = await web.client.get(
        f"{BASE}/ai-spend", params={"from": "2026-10-01", "to": "2026-10-26", "group": "model"}
    )

    check(bot, "/admin/integrations/spend", "get")
    check(ensemble, "/admin/integrations/ai-spend", "get")
    assert dict(crm.last("GET", "spend").url.params) == {"days": "14"}
    assert dict(crm.last("GET", "admin/ai-spend").url.params) == {
        "group": "model",
        "from": "2026-10-01",
        "to": "2026-10-26",
    }
    assert "Демо-Депо" not in bot.text
    assert "top_leads" not in bot.text
    assert "by_system" not in ensemble.text
    assert (await web.client.get(f"{BASE}/spend", params={"days": 0})).status_code == 422
    assert (await web.client.get(f"{BASE}/ai-spend", params={"group": "x"})).status_code == 422


async def test_ai_spend_period_error_and_litellm_down(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.error("GET", "admin/ai-spend", 422, "validation_failed", "ai_spend_period", field="from")

    period = await web.client.get(f"{BASE}/ai-spend", params={"from": "2020-01-01"})

    assert period.status_code == 422
    assert period.json()["code"] == "VALIDATION_FAILED"
    assert period.json()["details"]["reason"] == "ai_spend_period"
    assert period.json()["details"]["fields"] == ["from"]

    crm.error("GET", "admin/ai-spend", 502, "upstream_unavailable", "litellm_unavailable")
    down = await web.client.get(f"{BASE}/ai-spend")
    assert down.status_code == 502
    check(down, "/admin/integrations/ai-spend", "get")
    assert down.json()["code"] == "INTEGRATION_FAILED"
    assert down.json()["details"]["reason"] == "litellm_unavailable"


# --- хранилище, бэкапы, состояние ---------------------------------------------------------------


async def test_backup_request_is_accepted(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/backups")

    assert response.status_code == 202
    check(response, "/admin/integrations/backups", "post")
    assert response.json()["requested_at"] == "2026-10-26T09:00:00Z"


async def test_backup_request_refused_by_crm_is_a_conflict(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    crm.error("POST", "system/backups", 409, "conflict", "backup_unavailable")
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/backups")

    assert response.status_code == 409
    check(response, "/admin/integrations/backups", "post")
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == "backup_unavailable"


async def test_system_status_components(web: Web, crm: CrmIntegrationsFake) -> None:
    await web.login(["ADMIN"])

    response = await web.client.get(f"{BASE}/system")

    assert response.json()["status"] == "ok"
    assert [c["key"] for c in response.json()["components"]] == ["database", "bot"]


# --- ошибки CRM в едином формате ----------------------------------------------------------------


async def test_wrong_password_is_a_named_error_on_the_password_field(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    crm.error(
        "POST",
        "integrations/erp/rotate",
        422,
        "validation_failed",
        "wrong_password",
        field="password",
    )
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/erp/rotate", json={"password": PASSWORD})

    assert response.status_code == 422
    check(response, "/admin/integrations/erp/rotate", "post")
    assert response.json() == {
        "code": "WRONG_PASSWORD",
        "message": "Пароль указан неверно.",
        "source": "crm",
        "details": {"fields": ["password"], "reason": "wrong_password"},
    }


async def test_account_locked_after_wrong_passwords(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    crm.answer(
        "POST",
        "integrations/erp/rotate",
        423,
        {
            "code": "account_locked",
            "message": "locked",
            "details": {"until": "2099-01-01T00:00:00+00:00"},
        },
    )
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/erp/rotate", json={"password": PASSWORD})

    assert response.status_code == 423
    check(response, "/admin/integrations/erp/rotate", "post")
    assert response.json()["code"] == "ACCOUNT_LOCKED"
    assert int(response.headers["retry-after"]) > 0


@pytest.mark.parametrize(
    ("reason", "code", "path", "url"),
    [
        ("erp_not_configured", "NOT_CONFIGURED", "integrations/erp/check", "erp/check"),
        ("smtp_not_configured", "NOT_CONFIGURED", "integrations/smtp/check", "smtp/check"),
        (
            "secrets_key_missing",
            "SECRETS_KEY_MISSING",
            "integrations/smtp/test-send",
            "smtp/test-send",
        ),
    ],
)
async def test_state_conflicts_have_their_own_codes(
    web: Web,
    crm: CrmIntegrationsFake,
    check: ContractChecker,
    reason: str,
    code: str,
    path: str,
    url: str,
) -> None:
    crm.error("POST", path, 409, "conflict", reason)
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/{url}")

    assert response.status_code == 409
    assert response.json()["code"] == code
    assert response.json()["details"]["reason"] == reason
    check(response, f"/admin/integrations/{url}", "post")


@pytest.mark.parametrize(
    ("reason", "path", "url"),
    [
        ("erp_unavailable", "integrations/erp/check", "erp/check"),
        ("erp_unauthorized", "integrations/erp/check", "erp/check"),
        ("smtp_auth_failed", "integrations/smtp/check", "smtp/check"),
        ("smtp_tls_failed", "integrations/smtp/check", "smtp/check"),
    ],
)
async def test_probe_failure_502_is_integration_failed_not_crm_down(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker, reason: str, path: str, url: str
) -> None:
    """502 CRM на пробе — результат проверки (`details.reason`), а не «CRM недоступна» (503)."""
    crm.error("POST", path, 502, "upstream_unavailable", reason)
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/{url}")

    assert response.status_code == 502
    check(response, f"/admin/integrations/{url}", "post")
    assert response.json()["code"] == "INTEGRATION_FAILED"
    assert response.json()["source"] == "crm"
    assert response.json()["details"]["reason"] == reason


@pytest.mark.parametrize(
    ("reason", "field", "path", "url", "body"),
    [
        (
            "erp_invalid_url",
            "base_url",
            "integrations/erp/pair",
            "erp/pair",
            {"base_url": "ftp://x", "password": PASSWORD},
        ),
        (
            "erp_pairing_code_invalid",
            "code",
            "integrations/erp/pair",
            "erp/pair",
            {"base_url": "http://x", "code": "1", "password": PASSWORD},
        ),
        (
            "smtp_invalid_host",
            "host",
            "integrations/smtp",
            "smtp",
            {"host": "bad host", "password": PASSWORD},
        ),
    ],
)
async def test_field_errors_name_the_field(
    web: Web,
    crm: CrmIntegrationsFake,
    check: ContractChecker,
    reason: str,
    field: str,
    path: str,
    url: str,
    body: dict[str, Any],
) -> None:
    crm.error(
        "POST" if "pair" in url else "PUT", path, 422, "validation_failed", reason, field=field
    )
    await web.login(["ADMIN"])

    response = await web.send("POST" if "pair" in url else "PUT", f"{BASE}/{url}", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"]["fields"] == [field]
    assert response.json()["details"]["reason"] == reason


async def test_crm_refusal_is_forbidden_with_crm_source(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    """Директору CRM не отдаёт модели (нет `models:read`): BFF переводит отказ, а не прячет его."""
    crm.error("GET", "models", 403, "forbidden")
    await web.login(["DIRECTOR"])

    response = await web.client.get(f"{BASE}/models")

    assert response.status_code == 403
    check(response, "/admin/integrations/models", "get")
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["source"] == "crm"


async def test_crm_5xx_and_garbage_are_backend_unavailable(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    await web.login(["ADMIN"])
    crm.answer("GET", "integrations/erp", 500, {"code": "x", "message": "x", "details": {}})
    broken = await web.client.get(f"{BASE}/erp")
    crm.answer("GET", "integrations/smtp", 200, {"configured": "maybe"})
    garbage = await web.client.get(f"{BASE}/smtp")
    crm.overrides[("GET", "/api/v1/integrations/telegram")] = httpx.Response(200, content=b"<html>")
    html = await web.client.get(f"{BASE}/telegram")

    for response, template in (
        (broken, "erp"),
        (garbage, "smtp"),
        (html, "telegram"),
    ):
        assert response.status_code == 503, template
        check(response, f"/admin/integrations/{template}", "get")
        assert response.json()["code"] == "BACKEND_UNAVAILABLE"
        assert response.json()["source"] == "crm"


async def test_errors_never_contain_submitted_secrets(web: Web, crm: CrmIntegrationsFake) -> None:
    await web.login(["ADMIN"])
    token = "9:" + fresh_secret("bot", 24)
    crm.error(
        "PUT",
        "integrations/telegram/token",
        422,
        "validation_failed",
        "invalid_bot_token",
        field="token",
    )

    response = await web.send(
        "PUT", f"{BASE}/telegram/token", json={"token": token, "password": PASSWORD}
    )

    assert response.status_code == 422
    assert token not in response.text
    assert PASSWORD not in response.text


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(
            502, content=b"<html>Bad Gateway</html>", headers={"content-type": "text/html"}
        ),
        httpx.Response(502),
        httpx.Response(502, json=["not", "an", "app", "error"]),
        httpx.Response(503, json={"code": "x", "message": "x", "details": {}}),
        httpx.Response(504, content=b"gateway timeout"),
    ],
)
async def test_proxy_gateway_errors_on_probe_stay_crm_unavailable(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker, answer: httpx.Response
) -> None:
    """502/503/504 прокси — не итог проверки: «CRM недоступна» (503), а не INTEGRATION_FAILED."""
    crm.overrides[("POST", "/api/v1/integrations/smtp/check")] = answer
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/smtp/check")

    assert response.status_code == 503
    check(response, "/admin/integrations/smtp/check", "post")
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"
    assert response.json()["source"] == "crm"


async def test_network_failure_on_probe_is_crm_unavailable(
    web: Web, crm: CrmIntegrationsFake, check: ContractChecker
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    crm.overrides[("POST", "/api/v1/integrations/erp/check")] = refuse
    await web.login(["ADMIN"])

    response = await web.send("POST", f"{BASE}/erp/check")

    assert response.status_code == 503
    check(response, "/admin/integrations/erp/check", "post")
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"

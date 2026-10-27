"""Центр внешних сервисов (M3-CRM-12, ADR-0024) на реальном Postgres: API, роли, проверка сейчас,
инциденты и оповещения с антиспамом, выключатели (пароль, аудит, LiteLLM через respx), сводка на
«Состоянии системы». Внешние сервисы — подставные (respx), платных вызовов нет."""

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError, Reason
from app.domain.external_incidents import AlertText
from app.domain.system_status import ErpExternal, ErpFacts
from app.main import create_app
from app.models.auth import AuditLog, User
from app.models.email import EmailLog
from app.models.external_services import (
    ExternalCauseAlert,
    ExternalServiceCheck,
    ExternalServiceIncident,
    ExternalServiceSwitch,
)
from app.security.secrets_store import SecretCipher
from app.services.external_services.wiring import build_checks
from app.services.mail import MailService
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration

URL = "/api/v1/admin/external-services"
MODEL_INFO = {
    "data": [
        {
            "model_name": "dialog-model",
            "litellm_params": {"model": "anthropic/claude-sonnet-5-5"},
            "model_info": {"id": "rt-dialog", "db_model": True},
        },
        {
            "model_name": "fallback-model",
            "litellm_params": {"model": "gemini/gemini-3.8-flash"},
            "model_info": {"id": "rt-fallback", "db_model": True},
        },
        {
            "model_name": "embed-model",
            "litellm_params": {"model": "gemini/gemini-embedding-2"},
            "model_info": {"id": "rt-embed", "db_model": True},
        },
    ]
}


class FakeAlerts:
    def __init__(self) -> None:
        self.sent: list[tuple[str, AlertText]] = []

    async def send(self, alert: AlertText, key: str) -> bool:
        self.sent.append((key, alert))
        return True


class FakeTransport:
    async def check(self, connection: Any) -> Any:
        raise AssertionError("SMTP is not used here")

    async def send(self, connection: Any, to: str, subject: str, body: str) -> None:
        return None


@pytest.fixture
def base(live_settings: Settings) -> str:
    return str(live_settings.litellm_base_url).rstrip("/")


@pytest.fixture
def docling(live_settings: Settings) -> str:
    return f"{str(live_settings.docling_url).rstrip('/')}/health"


@pytest.fixture
def gateway(base: str) -> Iterator[respx.MockRouter]:
    with respx.mock(assert_all_called=False) as router:
        router.get(f"{base}/model/info").mock(return_value=httpx.Response(200, json=MODEL_INFO))
        yield router


@pytest.fixture
def alerts() -> FakeAlerts:
    return FakeAlerts()


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    gateway: respx.MockRouter,
    alerts: FakeAlerts,
) -> Iterator[TestClient]:
    app = create_app(live_settings)
    with TestClient(app) as test_client:
        app.state.bot = None
        container = app.state.container
        checks = build_checks(container)
        checks._alerts = alerts  # type: ignore[assignment]
        container.__dict__["external_checks"] = checks
        yield test_client


BOT_TOKEN = "123456:fake-fix66-token"  # фиктивный, в сеть не уходит


@pytest.fixture
def webhook_client(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    gateway: respx.MockRouter,
    alerts: FakeAlerts,
) -> Iterator[TestClient]:
    """Режим webhook с пустым адресом (FIX-66): бот не стартует и в Bot API не ходит."""
    settings = live_settings.model_copy(
        update={
            "telegram_mode": "webhook",
            "telegram_webhook_url": "",
            "telegram_webhook_secret": SecretStr("fix66-webhook-secret"),
            "telegram_bot_token": SecretStr(BOT_TOKEN),
        }
    )
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = app.state.container
        checks = build_checks(container)
        checks._alerts = alerts  # type: ignore[assignment]
        container.__dict__["external_checks"] = checks
        yield test_client


async def headers(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> dict[str, str]:
    account, password = await make_user(sessions, f"{role}@railtech.uz", [role])
    return login(client, account.email, password)


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_only_admin(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> None:
    assert client.get(URL).status_code == 401
    auth = await headers(sessions, client, role)
    assert client.get(URL, headers=auth).status_code == 403
    assert client.get(f"{URL}/telegram", headers=auth).status_code == 403
    assert client.post(f"{URL}/docling/check", headers=auth).status_code == 403
    body = {"password": PASSWORD}
    assert client.post(f"{URL}/telegram/disable", json=body, headers=auth).status_code == 403
    assert client.post(f"{URL}/telegram/enable", json=body, headers=auth).status_code == 403


async def test_registry_before_first_check(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await headers(sessions, client, "admin")
    response = client.get(URL, headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    services = {s["key"]: s for s in body["services"]}
    assert {"telegram", "litellm", "vendor.anthropic", "vendor.gemini", "mail", "s3"} <= set(
        services
    )
    assert services["telegram"]["status"] == "unknown"
    assert "Не проверено — нажмите «Проверить»" in services["telegram"]["summary"]
    assert services["telegram"]["state"] == "not_checked"
    erp = services["erp.cbu_rates"]
    assert (erp["status"], erp["source"], erp["switch"]["kind"]) == ("unknown", "erp", "erp")
    assert services["erp.sentry"]["switch"] is None  # Sentry выключить нельзя
    assert services["vendor.gemini"]["switch"]["available"] is False  # вендор запасной модели
    assert services["vendor.anthropic"]["switch"]["available"] is True
    assert body["checked_at"] is None
    assert client.get(f"{URL}/nope", headers=auth).status_code == 404


async def test_check_now_opens_and_closes_incident_without_alert_noise(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    auth = await headers(sessions, client, "admin")
    route = gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))

    failed = client.post(f"{URL}/docling/check", headers=auth)
    assert failed.status_code == 200, failed.text
    detail = failed.json()
    assert detail["service"]["status"] == "fail"
    assert detail["service"]["hint"]
    assert detail["service"]["incident"]["ended_at"] is None
    assert [c["tier"] for c in detail["checks"]] == ["manual"]
    assert len(detail["days"]) == 7
    # Повторный сбой — тот же инцидент; «Сломано» меньше 15 минут — оповещения нет.
    client.post(f"{URL}/docling/check", headers=auth)
    assert alerts.sent == []

    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    recovered = client.post(f"{URL}/docling/check", headers=auth).json()
    assert recovered["service"]["status"] == "ok"
    assert recovered["service"]["incident"] is None
    (incident,) = recovered["incidents"]
    assert incident["ended_at"] is not None  # «восстановлено в …» в журнале инцидентов
    assert not incident["alerted"]
    assert alerts.sent == []  # о сбое не сообщали — и «восстановлено» не нужно
    assert recovered["service"]["last_recovered_at"] is not None
    assert recovered["service"]["uptime_24h"] == pytest.approx(1 / 3, abs=0.01)

    route.mock(side_effect=httpx.ConnectError("refused"))
    client.post(f"{URL}/docling/check", headers=auth)
    async with sessions() as session:
        rows = (await session.scalars(select(ExternalServiceIncident))).all()
    assert len(rows) == 2
    assert alerts.sent == []


T0 = datetime.now(UTC) - timedelta(hours=3)  # подменённое время: все проходы — «в прошлом»


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


async def run_at(client: TestClient, moment: datetime, *keys: str) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    await container.external_checks.run("manual", moment, keys=list(keys))


async def docling_checks(sessions: async_sessionmaker[AsyncSession]) -> list[datetime]:
    async with sessions() as session:
        stmt = select(ExternalServiceCheck.checked_at).where(
            ExternalServiceCheck.service_key == "docling"
        )
        return sorted((await session.scalars(stmt)).all())


async def test_cause_alert_waits_fifteen_minutes_fires_once_and_restores_once(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    route = gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))
    for minutes in (0, 5, 14):
        await run_at(client, at(minutes), "docling")
    assert alerts.sent == []  # «Сломано» меньше 15 минут — тишина

    await run_at(client, at(16), "docling")
    assert [key for key, _ in alerts.sent] == ["docling:server_down"]
    broken = alerts.sent[0][1]
    assert broken.subject.startswith("⚠️ Сломано: ")
    assert "хостинг" in broken.plain
    assert "refused" not in broken.plain  # сырой ответ в оповещение не идёт

    # Дальше — ни одного повтора: ни на следующих проверках, ни после рестарта процесса.
    await run_at(client, at(30), "docling")
    container = client.app.state.container  # type: ignore[attr-defined]
    restarted = build_checks(container)
    restarted._alerts = alerts  # type: ignore[assignment]
    await restarted.run("manual", at(45), keys=["docling"])
    await restarted.run("manual", at(120), keys=["docling"])
    assert len(alerts.sent) == 1

    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    await run_at(client, at(130), "docling")
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == ["⚠️ Сломано", "✅ Восстановлено"]
    assert "Не работало 2 ч 10 мин" in alerts.sent[1][1].plain  # от первого сбоя до возврата
    await run_at(client, at(131), "docling")
    assert len(alerts.sent) == 2

    async with sessions() as session:
        (cause_row,) = (await session.scalars(select(ExternalCauseAlert))).all()
        (incident,) = (await session.scalars(select(ExternalServiceIncident))).all()
    assert cause_row.cause_key == "docling:server_down"
    assert cause_row.ended_at is not None  # «восстановлено в …» в журнале
    assert cause_row.alerted_at is not None
    assert cause_row.recovery_alerted_at is not None
    assert incident.ended_at is not None
    assert incident.alerted_at is not None
    assert incident.recovery_alerted_at is not None

    # Снова сломалось, но меньше 15 минут и сразу починилось — без шума.
    route.mock(side_effect=httpx.ConnectError("refused"))
    await run_at(client, at(140), "docling")
    await run_at(client, at(150), "docling")
    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    await run_at(client, at(152), "docling")
    assert len(alerts.sent) == 2


async def test_failed_alert_delivery_is_retried_not_lost(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))
    deliver = False

    async def send(alert: AlertText, key: str) -> bool:
        alerts.sent.append((key, alert)) if deliver else None
        return deliver

    alerts.send = send  # type: ignore[method-assign]
    await run_at(client, at(0), "docling")
    await run_at(client, at(20), "docling")  # попытка есть, но ни Telegram, ни почта не доставили
    assert alerts.sent == []
    deliver = True
    await run_at(client, at(21), "docling")
    await run_at(client, at(22), "docling")
    assert [key for key, _ in alerts.sent] == ["docling:server_down"]


async def test_groups_name_the_cause_the_owner_and_the_action(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
) -> None:
    auth = await headers(sessions, client, "admin")
    gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))
    response = client.post(f"{URL}/docling/check", headers=auth)
    assert response.status_code == 200, response.text
    body = client.get(URL, headers=auth).json()
    assert body["stand"] is False
    (group,) = [g for g in body["groups"] if g["id"] == "docling:server_down"]
    assert (group["state"], group["owner"], group["action"]) == (
        "broken",
        "hosting",
        "write_hosting",
    )
    assert group["more_actions"] == ["recheck"]
    assert group["since"] is not None
    assert "Запустить docling вместе с ансамблем" in group["detail"]
    assert "администратору сервера" not in group["detail"]
    assert "Запустить docling вместе с ансамблем" in group["message"]
    assert group["technical"]  # сырая причина — только отдельным полем, свёрнуто в интерфейсе
    assert group["headline"] not in group["technical"]
    service = {s["key"]: s for s in body["services"]}["docling"]
    assert service["cause_key"] == "docling:server_down"
    assert service["state"] == "broken"
    assert service["since"] is not None


@pytest.fixture
def stand_client(
    sessions: async_sessionmaker[AsyncSession],
    live_settings: Settings,
    gateway: respx.MockRouter,
    alerts: FakeAlerts,
) -> Iterator[TestClient]:
    """Стенд (`APP_ENV=dev`): сбои, которые на стенде чинить некому, — «ожидаемо»."""
    app = create_app(live_settings.model_copy(update={"app_env": "dev"}))
    with TestClient(app) as test_client:
        app.state.bot = None
        container = app.state.container
        checks = build_checks(container)
        checks._alerts = alerts  # type: ignore[assignment]
        container.__dict__["external_checks"] = checks
        yield test_client


async def test_expected_on_stand_is_grey_and_never_alerts(
    sessions: async_sessionmaker[AsyncSession],
    stand_client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    auth = await headers(sessions, stand_client, "admin")
    gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))
    for minutes in (0, 20, 60):
        await run_at(stand_client, at(minutes), "docling")
    assert alerts.sent == []
    container = stand_client.app.state.container  # type: ignore[attr-defined]
    container.external_view.invalidate()
    body = (await container.external_view.list(at(61))).model_dump(mode="json")
    service = {s["key"]: s for s in body["services"]}["docling"]
    assert (service["status"], service["state"]) == ("fail", "expected")
    assert body["stand"] is True
    assert body["summary"]["fail"] == 0  # не сбой — не «Требует внимания»
    (group,) = [g for g in body["groups"] if g["id"] == "docling:server_down"]
    assert group["state"] == "expected"
    assert stand_client.get(URL, headers=auth).status_code == 200
    async with sessions() as session:
        assert (await session.scalars(select(ExternalCauseAlert))).all() == []


async def test_broken_service_is_rechecked_with_decay_and_clears_itself(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
) -> None:
    route = gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))
    container = client.app.state.container  # type: ignore[attr-defined]
    seconds = {0: 1, 30: 1, 60: 2, 120: 2, 180: 3, 300: 3, 480: 4, 1000: 4, 1380: 5, 2000: 5}
    # (момент в секундах от T0) -> сколько проверок docling должно быть записано к этому моменту
    for sec, expected in seconds.items():
        await container.external_checks.run("cheap", T0 + timedelta(seconds=sec))
        assert len(await docling_checks(sessions)) == expected, sec

    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    await container.external_checks.run("cheap", T0 + timedelta(seconds=2280))  # 15 мин спустя
    assert len(await docling_checks(sessions)) == 6
    await container.external_checks.run("cheap", T0 + timedelta(seconds=2340))
    assert len(await docling_checks(sessions)) == 7  # снова каждую минуту
    async with sessions() as session:
        stmt = select(ExternalServiceIncident).where(
            ExternalServiceIncident.service_key == "docling"
        )
        (incident,) = (await session.scalars(stmt)).all()
    assert incident.ended_at is not None  # строка снялась сама


async def test_heavy_only_service_is_rechecked_by_its_own_schedule(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    async with sessions() as session, session.begin():
        session.add(
            ExternalServiceCheck(
                service_key="tls.crm", checked_at=T0, tier="heavy", status="fail", summary="x"
            )
        )
    assert await container.external_checks.recheck_broken(T0 + timedelta(seconds=30)) == []
    results = await container.external_checks.recheck_broken(T0 + timedelta(minutes=1))
    assert [r.key for r in results] == ["tls.crm"]
    # теперь по умолчанию (localhost без TLS) — «не применимо», не fail: дальше не перепроверяется
    assert await container.external_checks.recheck_broken(T0 + timedelta(minutes=2)) == []


async def test_telegram_webhook_not_configured_is_an_incident_without_token_leak(
    sessions: async_sessionmaker[AsyncSession],
    webhook_client: TestClient,
    gateway: respx.MockRouter,
    alerts: FakeAlerts,
) -> None:
    """FIX-66: пустой адрес вебхука — инцидент с подсказкой; токена нет в API и оповещении."""
    from structlog.testing import capture_logs

    auth = await headers(sessions, webhook_client, "admin")
    api = "https://api.telegram.org"
    gateway.get(f"{api}/bot{BOT_TOKEN}/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"username": "rt_bot"}})
    )
    info = gateway.get(f"{api}/bot{BOT_TOKEN}/getWebhookInfo").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "url": "",
                    "last_error_date": int(datetime.now(UTC).timestamp()),
                    "last_error_message": f"Bad Gateway {api}/bot{BOT_TOKEN}/x",
                },
            },
        )
    )
    with capture_logs() as logs:
        response = webhook_client.post(f"{URL}/telegram/check", headers=auth)
    assert response.status_code == 200, response.text
    service = response.json()["service"]
    assert service["status"] == "fail"
    assert "Вебхук Telegram не настроен" in service["summary"]
    assert service["hint"]
    assert service["fix_path"] is None  # «Исправить» в «Подключения» здесь не помогает
    assert "_no_fix" not in service["metrics"]
    assert service["incident"]["ended_at"] is None
    assert service["state"] == "broken"
    assert (service["owner"], service["action"]) == ("hosting", "write_hosting")
    assert info.call_count == 1
    assert alerts.sent == []  # оповещение — после 15 минут «Сломано» (W15-H3)

    listing = webhook_client.get(URL, headers=auth)
    for text in (response.text, listing.text, repr(alerts.sent), repr(logs)):
        assert BOT_TOKEN not in text
        assert f"/bot{BOT_TOKEN.split(':')[0]}" not in text
    assert listing.status_code == 200
    assert gateway.calls  # проверка прошла через подставной Bot API
    # Бот не запускался и вебхук никто не трогал: ни setWebhook, ни deleteWebhook.
    urls = [str(c.request.url) for c in gateway.calls]
    assert not [u for u in urls if u.endswith(("/setWebhook", "/deleteWebhook"))]


async def test_background_pass_records_all_crm_services(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await headers(sessions, client, "admin")
    container = client.app.state.container  # type: ignore[attr-defined]
    results = await container.external_checks.run("cheap", datetime.now(UTC))
    keys = {r.key for r in results}
    assert {"telegram", "litellm", "langfuse", "mail", "s3", "docling", "backup"} <= keys
    assert not any(k.startswith("tls.") for k in keys)
    assert {f"erp.{c}" for c in ("cbu_rates", "customs_tariff", "mail", "litellm", "s3")} <= keys
    body = client.get(URL, headers=auth).json()
    assert body["checked_at"] is not None
    assert sum(body["summary"].values()) - body["summary"]["disabled"] == len(body["services"])

    status = client.get("/api/v1/system/status", headers=auth).json()
    summary = next(c for c in status["components"] if c["key"] == "external_services")
    assert summary["title"] == "Внешние сервисы"


async def test_telegram_switch_needs_password_and_is_audited(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await headers(sessions, client, "admin")
    wrong = client.post(f"{URL}/telegram/disable", json={"password": "nope"}, headers=auth)
    assert wrong.status_code == 422
    assert wrong.json()["details"]["reason"] == "wrong_password"

    off = client.post(
        f"{URL}/telegram/disable",
        json={"password": PASSWORD, "reason": "бот отвечает ерунду"},
        headers=auth,
    )
    assert off.status_code == 200, off.text
    switch = off.json()["switch"]
    assert (switch["disabled"], switch["reason"]) == (True, "бот отвечает ерунду")
    assert switch["changed_by"] == "admin"
    container = client.app.state.container  # type: ignore[attr-defined]
    assert await container.telegram_bot() is None  # исходящие на паузе

    on = client.post(f"{URL}/telegram/enable", json={"password": PASSWORD}, headers=auth)
    assert on.json()["switch"]["disabled"] is False
    async with sessions() as session:
        actions = (
            await session.scalars(
                select(AuditLog.action)
                .where(AuditLog.entity_type == "external_service")
                .order_by(AuditLog.id)
            )
        ).all()
    assert actions == ["external_service.disable", "external_service.enable"]

    no_switch = client.post(f"{URL}/litellm/disable", json={"password": PASSWORD}, headers=auth)
    assert no_switch.status_code == 409
    assert no_switch.json()["details"]["reason"] == "service_not_switchable"


async def test_vendor_switch_reroutes_aliases_in_gateway(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    base: str,
) -> None:
    auth = await headers(sessions, client, "admin")
    update = gateway.post(f"{base}/config/update").mock(
        return_value=httpx.Response(200, json={"message": "Config updated successfully"})
    )
    block = gateway.post(f"{base}/model/block").mock(return_value=httpx.Response(200, json={}))

    off = client.post(f"{URL}/vendor.anthropic/disable", json={"password": PASSWORD}, headers=auth)
    assert off.status_code == 200, off.text
    assert json.loads(update.calls.last.request.content) == {
        "router_settings": {"model_group_alias": {"dialog-model": "fallback-model"}}
    }
    assert not block.called  # эмбеддинги у Gemini — блокировать нечего
    async with sessions() as session:
        row = await session.get(ExternalServiceSwitch, "vendor.anthropic")
    assert row is not None
    assert row.state == {"redirected": ["dialog-model"], "blocked": []}

    gemini = client.post(f"{URL}/vendor.gemini/disable", json={"password": PASSWORD}, headers=auth)
    assert gemini.status_code == 409
    assert gemini.json()["details"]["reason"] == "service_not_switchable"
    assert "запасн" in gemini.json()["details"]["detail"]

    # Минутная проверка сверяет шлюз: alias сбросили снаружи — CRM возвращает его сама.
    gateway.get(f"{base}/router/settings").mock(
        return_value=httpx.Response(200, json={"current_values": {"model_group_alias": {}}})
    )
    container = client.app.state.container  # type: ignore[attr-defined]
    assert await container.external_switches.reconcile() is True

    on = client.post(f"{URL}/vendor.anthropic/enable", json={"password": PASSWORD}, headers=auth)
    assert on.status_code == 200, on.text
    assert json.loads(update.calls.last.request.content) == {
        "router_settings": {"model_group_alias": {}}
    }


async def test_vendor_switch_reports_gateway_failure(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    base: str,
) -> None:
    auth = await headers(sessions, client, "admin")
    gateway.post(f"{base}/config/update").mock(side_effect=httpx.ConnectError("refused"))
    response = client.post(
        f"{URL}/vendor.anthropic/disable", json={"password": PASSWORD}, headers=auth
    )
    assert response.status_code == 502
    assert response.json()["details"]["reason"] == "litellm_unavailable"
    async with sessions() as session:
        assert await session.get(ExternalServiceSwitch, "vendor.anthropic") is None


async def test_mail_pause_holds_and_enable_resumes_queue(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, live_settings: Settings
) -> None:
    auth = await headers(sessions, client, "admin")
    queued: list[int] = []
    cipher = SecretCipher("k" * 64)
    container = client.app.state.container  # type: ignore[attr-defined]

    async def enqueue(email_log_id: int) -> int:
        queued.append(email_log_id)
        return email_log_id

    container.__dict__["mail_service"] = MailService(
        container.session_factory,
        container.secrets_store,
        cipher,
        live_settings,
        container.settings_service,
        FakeTransport(),
        enqueue,
        paused=container._mail_paused,
    )
    container.__dict__.pop("external_switches", None)
    off = client.post(f"{URL}/mail/disable", json={"password": PASSWORD}, headers=auth)
    assert off.status_code == 200, off.text
    async with sessions() as session, session.begin():
        row = EmailLog(
            to_email="a@railtech.uz",
            subject="s",
            template="test",
            lang="ru",
            status="queued",
            body_ciphertext=cipher.encrypt("body"),
            created_at=datetime.now(UTC) - timedelta(minutes=1),
        )
        session.add(row)
    container.switch_board.invalidate()
    on = client.post(f"{URL}/mail/enable", json={"password": PASSWORD}, headers=auth)
    assert on.status_code == 200, on.text
    assert len(queued) == 1


async def test_erp_sync_failures_land_in_the_feed_not_in_the_users_answer(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, alerts: FakeAlerts
) -> None:
    """FIX-11: ошибка провижининга — сбой строки «Синхронизация с ERP» и оповещение админу."""
    auth = await headers(sessions, client, "admin")
    manager, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    async with sessions() as session, session.begin():
        row = await session.get(User, manager.id)
        assert row is not None
        row.platform_access = ["crm", "erp"]

    ok = client.post(f"{URL}/erp_sync/check", headers=auth).json()["service"]
    assert (ok["status"], ok["key"]) == ("ok", "erp_sync")

    async with sessions() as session, session.begin():
        row = await session.get(User, manager.id)
        assert row is not None
        row.erp_sync_error = "erp_provision_user: erp_unavailable: timeout"

    failed = client.post(f"{URL}/erp_sync/check", headers=auth).json()["service"]
    assert failed["status"] == "fail"
    assert failed["error"] == "erp_provision_user: erp_unavailable: timeout"
    assert failed["hint"]
    assert failed["fix_path"] == "/integrations?tab=erp"
    assert alerts.sent == []  # «Сломано» меньше 15 минут — без оповещения (W15-H3)

    async with sessions() as session, session.begin():
        row = await session.get(User, manager.id)
        assert row is not None
        row.erp_sync_error = None
    healed = client.post(f"{URL}/erp_sync/check", headers=auth).json()["service"]
    assert healed["status"] == "ok"


async def test_erp_handoff_failures_land_in_the_feed_with_the_client_and_the_code(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, alerts: FakeAlerts
) -> None:
    """FIX-31: ошибка передачи клиента (409 ИНН) — сбой строки «Передача клиентов в ERP»."""
    from app.models.clients import Client

    auth = await headers(sessions, client, "admin")
    idle = client.post(f"{URL}/erp_handoff/check", headers=auth).json()["service"]
    assert (idle["status"], idle["key"]) == ("off", "erp_handoff")  # ERP не подключена, передач нет

    async with sessions() as session, session.begin():
        row = Client(
            name="ООО Дубль",
            erp_handoff_status="failed",
            erp_handoff_error="erp_inn_conflict",
        )
        session.add(row)
        await session.flush()
        client_id = row.id

    failed = client.post(f"{URL}/erp_handoff/check", headers=auth).json()["service"]
    assert failed["status"] == "fail"
    assert failed["error"] == "ООО Дубль: erp_inn_conflict"
    assert failed["hint"]
    assert failed["fix_path"] == "/clients"
    assert alerts.sent == []

    async with sessions() as session, session.begin():
        saved = await session.get(Client, client_id)
        assert saved is not None
        saved.erp_handoff_status, saved.erp_handoff_error = "done", None
    healed = client.post(f"{URL}/erp_handoff/check", headers=auth).json()["service"]
    assert healed["status"] == "off"


INSERT_INBOX = """
INSERT INTO rt_bus_inbox (event_id, type, source, publisher, correlation_id, envelope, status,
                          attempts, error, received_at, updated_at)
VALUES (:id, 'uz.railtech.erp.quote.sent.v1', 'rt://erp', 'erp', 'c-1', CAST('{}' AS jsonb),
        :status, 4, :error, :at, :at)
"""
INSERT_DELIVERY = """
INSERT INTO rt_bus_delivery (event_id, event_type, subscriber, status, attempts, last_error,
                             created_at, updated_at)
VALUES (:id, 'uz.railtech.crm.client.updated.v1', 'erp', 'dead', 7, :error, :at, :at)
"""


async def test_erp_events_failures_land_in_the_feed_and_heal_when_old(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, alerts: FakeAlerts
) -> None:
    """B4: необработанное событие ERP (inbox `failed`) и недоставленное ERP событие CRM (`dead`)
    — сбой строки «События ERP»; старше недели в счёт не идут."""
    from sqlalchemy import text

    auth = await headers(sessions, client, "admin")
    quiet = client.post(f"{URL}/erp_events/check", headers=auth).json()["service"]
    assert (quiet["status"], quiet["key"]) == ("ok", "erp_events")

    async with sessions() as session, session.begin():
        await session.execute(
            text(INSERT_INBOX),
            {
                "id": uuid.UUID("00000000-0000-4000-8000-000000000001"),
                "status": "failed",
                "error": "ErpEventError: company mismatch: client #1 is erp company #5",
                "at": datetime.now(UTC),
            },
        )
    failed = client.post(f"{URL}/erp_events/check", headers=auth).json()["service"]
    assert failed["status"] == "fail"
    assert "company mismatch" in failed["error"]
    assert failed["hint"]
    assert alerts.sent == []

    async with sessions() as session, session.begin():  # разобрано давно: в окно недели не входит
        await session.execute(
            text("UPDATE rt_bus_inbox SET received_at = :old"),
            {"old": datetime.now(UTC) - timedelta(days=30)},
        )
    healed = client.post(f"{URL}/erp_events/check", headers=auth).json()["service"]
    assert healed["status"] == "ok"

    async with sessions() as session, session.begin():
        await session.execute(
            text(INSERT_DELIVERY),
            {
                "id": uuid.UUID("00000000-0000-4000-8000-000000000002"),
                "error": "http 404",
                "at": datetime.now(UTC),
            },
        )
    dead = client.post(f"{URL}/erp_events/check", headers=auth).json()["service"]
    assert dead["status"] == "fail"
    assert "не доставлено ERP: 1" in dead["summary"]
    assert "http 404" in dead["error"]


# ── Сервисы ERP (M3-ERP-06) ──────────────────────────────────────────────────────────

ERP_NOW = datetime.now(UTC)


def erp_item(code: str, status: str = "ok", **kw: Any) -> ErpExternal:
    base: dict[str, Any] = {
        "code": code,
        "status": status,
        "enabled": True,
        "switchable": code != "sentry",
        "last_success_at": ERP_NOW - timedelta(hours=1),
        "last_error_at": None,
        "last_error": None,
        "ok_24h": 5,
        "errors_24h": 0,
    }
    return ErpExternal(**{**base, **kw})


def erp_facts(*items: ErpExternal, **kw: Any) -> ErpFacts:
    return ErpFacts(configured=True, status="ok", externals=items, **kw)


class FakeErpConnector:
    """Ответ ERP на /health подставной: проверки читают его вместо настоящего коннектора."""

    def __init__(self, facts: ErpFacts) -> None:
        self.facts = facts
        self.refreshed = 0

    async def health_facts(self) -> ErpFacts:
        return self.facts

    async def check(self) -> None:
        self.refreshed += 1

    async def resolution(self) -> Any:
        return SimpleNamespace(base_url="https://erp.test", connection=object())


class FakeErpSwitch:
    def __init__(self) -> None:
        self.calls: list[tuple[str, bool, str | None]] = []
        self.refuse: Exception | None = None

    async def set_switch(self, code: str, *, enabled: bool, reason: str | None) -> None:
        if self.refuse is not None:
            raise self.refuse
        self.calls.append((code, enabled, reason))


def attach_erp(
    client: TestClient, alerts: FakeAlerts, facts: ErpFacts
) -> tuple[Any, FakeErpSwitch]:
    container = client.app.state.container  # type: ignore[attr-defined]
    connector = FakeErpConnector(facts)
    container.__dict__["erp_connector"] = connector
    checks = build_checks(container)
    checks._alerts = alerts  # type: ignore[assignment]
    container.__dict__["external_checks"] = checks
    switch = FakeErpSwitch()
    container.external_switches._erp_switch = switch
    return connector, switch


async def test_erp_services_show_status_metrics_and_last_error(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, alerts: FakeAlerts
) -> None:
    auth = await headers(sessions, client, "admin")
    connector, _ = attach_erp(
        client,
        alerts,
        erp_facts(
            erp_item("cbu_rates"),
            erp_item(
                "mail",
                "degraded",
                last_error_at=ERP_NOW,
                last_error="SMTPServerDisconnected: connection unexpectedly closed",
                errors_24h=2,
            ),
            erp_item("s3", "disabled", enabled=False),
            erp_item("sentry", "disabled"),
        ),
    )
    container = client.app.state.container  # type: ignore[attr-defined]
    results = await container.external_checks.run("cheap", datetime.now(UTC))
    by_key = {r.key: r for r in results}
    assert by_key["erp.cbu_rates"].status == "ok"
    assert by_key["erp.customs_tariff"].status == "unknown"  # ERP про него не передала

    services = {s["key"]: s for s in client.get(URL, headers=auth).json()["services"]}
    mail = services["erp.mail"]
    assert (mail["status"], mail["source"], mail["system"]) == ("warn", "erp", "erp")
    assert mail["error"] == "SMTPServerDisconnected: connection unexpectedly closed"
    assert mail["hint"]
    assert "ERP" in mail["summary"] + mail["hint"]
    assert mail["metrics"]["ok_24h"] == 5
    assert mail["metrics"]["errors_24h"] == 2
    assert mail["checked_at"] is not None
    assert mail["stale"] is False
    assert services["erp.cbu_rates"]["status"] == "ok"
    assert (services["erp.s3"]["status"], services["erp.sentry"]["status"]) == ("off", "off")
    # Только сервисы ERP: токен Telegram в окружении CI не задан, его сбой — не предмет этого теста.
    assert [k for k, _ in alerts.sent if k.startswith("erp.")] == [], "degraded — не инцидент"

    # «Проверить сейчас» берёт свежий ответ ERP, а не кэш коннектора.
    fresh = client.post(f"{URL}/erp.mail/check", headers=auth)
    assert fresh.status_code == 200, fresh.text
    assert connector.refreshed == 1
    assert "manual" in [c["tier"] for c in fresh.json()["checks"]]


async def test_erp_service_failure_opens_one_incident_and_one_alert_then_recovers(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, alerts: FakeAlerts
) -> None:
    auth = await headers(sessions, client, "admin")
    failing = erp_item(
        "litellm",
        "fail",
        last_success_at=None,
        last_error_at=ERP_NOW,
        last_error="AI_GATEWAY_UNAVAILABLE",
        ok_24h=0,
        errors_24h=9,
    )
    connector, _ = attach_erp(client, alerts, erp_facts(failing))

    first = client.post(f"{URL}/erp.litellm/check", headers=auth).json()
    assert first["service"]["status"] == "fail"
    assert first["service"]["error"] == "AI_GATEWAY_UNAVAILABLE"
    assert first["service"]["incident"]["ended_at"] is None
    assert (first["service"]["owner"], first["service"]["action"]) == ("owner", "write_owner")
    client.post(f"{URL}/erp.litellm/check", headers=auth)  # повтор — тот же инцидент
    assert alerts.sent == []  # «Сломано» меньше 15 минут

    connector.facts = erp_facts(erp_item("litellm"))
    healed = client.post(f"{URL}/erp.litellm/check", headers=auth).json()
    assert healed["service"]["status"] == "ok"
    assert healed["service"]["incident"] is None
    assert alerts.sent == []

    connector.facts = erp_facts(failing)
    client.post(f"{URL}/erp.litellm/check", headers=auth)
    async with sessions() as session:
        rows = (await session.scalars(select(ExternalServiceIncident))).all()
    assert [r.service_key for r in rows] == ["erp.litellm", "erp.litellm"]


async def test_unreachable_or_missing_erp_does_not_open_incidents(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, alerts: FakeAlerts
) -> None:
    auth = await headers(sessions, client, "admin")
    container = client.app.state.container  # type: ignore[attr-defined]
    connector, _ = attach_erp(client, alerts, ErpFacts(configured=True, error="unavailable"))
    await container.external_checks.run("cheap", datetime.now(UTC))
    services = {s["key"]: s for s in client.get(URL, headers=auth).json()["services"]}
    assert services["erp.mail"]["status"] == "unknown"
    assert "ERP не отвечает" in services["erp.mail"]["summary"]

    connector.facts = ErpFacts(configured=False)
    await container.external_checks.run("cheap", datetime.now(UTC))
    container.external_view.invalidate()
    services = {s["key"]: s for s in client.get(URL, headers=auth).json()["services"]}
    assert services["erp.mail"]["status"] == "off"
    connector.facts = ErpFacts(configured=True, status="ok", externals=None)  # ERP до M3-ERP-06
    await container.external_checks.run("cheap", datetime.now(UTC))
    container.external_view.invalidate()
    services = {s["key"]: s for s in client.get(URL, headers=auth).json()["services"]}
    assert "не передаёт" in services["erp.mail"]["summary"]
    assert [k for k, _ in alerts.sent if k.startswith("erp.")] == []
    async with sessions() as session:
        incidents = (await session.scalars(select(ExternalServiceIncident))).all()
    assert [r.service_key for r in incidents if r.service_key.startswith("erp.")] == []


async def test_erp_service_switch_goes_to_erp_with_password_and_audit(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, alerts: FakeAlerts
) -> None:
    auth = await headers(sessions, client, "admin")
    _, erp_switch = attach_erp(client, alerts, erp_facts(erp_item("mail")))

    wrong = client.post(f"{URL}/erp.mail/disable", json={"password": "nope"}, headers=auth)
    assert wrong.status_code == 422
    assert erp_switch.calls == []

    off = client.post(
        f"{URL}/erp.mail/disable",
        json={"password": PASSWORD, "reason": "SMTP-ключ скомпрометирован"},
        headers=auth,
    )
    assert off.status_code == 200, off.text
    body = off.json()
    assert erp_switch.calls == [("mail", False, "SMTP-ключ скомпрометирован")]
    assert body["switch"]["kind"] == "erp"
    assert body["switch"]["disabled"] is True
    assert "письма" in body["switch"]["effect"]
    assert body["status"] == "off", "выключатель виден сразу, не через минуту"

    on = client.post(f"{URL}/erp.mail/enable", json={"password": PASSWORD}, headers=auth)
    assert on.status_code == 200, on.text
    assert erp_switch.calls[-1] == ("mail", True, None)
    assert on.json()["switch"]["disabled"] is False

    async with sessions() as session:
        actions = (
            await session.scalars(
                select(AuditLog.action)
                .where(AuditLog.entity_type == "external_service")
                .order_by(AuditLog.id)
            )
        ).all()
    assert actions == ["external_service.disable", "external_service.enable"]


async def test_erp_switch_refused_or_unreachable_is_not_recorded(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, alerts: FakeAlerts
) -> None:
    auth = await headers(sessions, client, "admin")
    _, erp_switch = attach_erp(client, alerts, erp_facts(erp_item("s3")))
    erp_switch.refuse = ConflictError(
        "erp does not know this switch", reason=Reason.SERVICE_NOT_SWITCHABLE, detail="обновите ERP"
    )
    refused = client.post(f"{URL}/erp.s3/disable", json={"password": PASSWORD}, headers=auth)
    assert refused.status_code == 409
    assert refused.json()["details"]["reason"] == "service_not_switchable"
    async with sessions() as session:
        assert await session.get(ExternalServiceSwitch, "erp.s3") is None
        audits = (
            await session.scalars(
                select(AuditLog).where(AuditLog.entity_type == "external_service")
            )
        ).all()
    assert audits == [], "ERP не подтвердила — ни строки, ни аудита"

    sentry = client.post(f"{URL}/erp.sentry/disable", json={"password": PASSWORD}, headers=auth)
    assert sentry.status_code == 409
    assert sentry.json()["details"]["reason"] == "service_not_switchable"

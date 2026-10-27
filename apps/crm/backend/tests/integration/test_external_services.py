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
        checks._collector._d.retry_delay_s = 0.0
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
        checks._collector._d.retry_delay_s = 0.0
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


async def test_short_failures_are_unstable_not_incidents_and_never_alert(
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
    assert detail["service"]["state"] == "unstable"  # «Сломано» — только после 15 мин подряд
    assert detail["service"]["hint"]
    assert detail["service"]["incident"] is None
    assert [c["tier"] for c in detail["checks"]] == ["manual"]
    assert len(detail["days"]) == 7
    client.post(f"{URL}/docling/check", headers=auth)
    assert alerts.sent == []

    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    recovered = client.post(f"{URL}/docling/check", headers=auth).json()
    assert recovered["service"]["status"] == "ok"
    assert recovered["service"]["state"] == "ok"
    assert recovered["incidents"] == []  # провал короче 15 минут — не инцидент
    assert alerts.sent == []
    assert recovered["service"]["uptime_24h"] == pytest.approx(1 / 3, abs=0.01)

    route.mock(side_effect=httpx.ConnectError("refused"))
    client.post(f"{URL}/docling/check", headers=auth)
    async with sessions() as session:
        assert (await session.scalars(select(ExternalServiceIncident))).all() == []
        assert (await session.scalars(select(ExternalCauseAlert))).all() == []
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
    await run_at(client, at(133), "docling")
    assert len(alerts.sent) == 1  # ok короче 5 минут — «Восстановлено» рано
    await run_at(client, at(135), "docling")
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == ["⚠️ Сломано", "✅ Восстановлено"]
    assert "Не работало 2 ч 10 мин" in alerts.sent[1][1].plain  # от первого сбоя до начала ok
    await run_at(client, at(136), "docling")
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
    async with sessions() as session:
        assert len((await session.scalars(select(ExternalCauseAlert))).all()) == 1


async def test_failed_alert_delivery_is_retried_not_lost(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    route = gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))
    deliver = False

    async def send(alert: AlertText, key: str) -> bool:
        if deliver:
            alerts.sent.append((key, alert))
        return deliver

    alerts.send = send  # type: ignore[method-assign]
    await run_at(client, at(0), "docling")
    await run_at(client, at(20), "docling")  # попытка есть, но ни Telegram, ни почта не доставили
    assert alerts.sent == []
    deliver = True
    await run_at(client, at(21), "docling")
    await run_at(client, at(22), "docling")
    assert [key for key, _ in alerts.sent] == ["docling:server_down"]

    # «Восстановлено» не доставлено сразу — не теряется, уходит следующим проходом и ровно один раз.
    deliver = False
    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    await run_at(client, at(30), "docling")
    await run_at(client, at(36), "docling")  # ok уже 6 минут — «Восстановлено», но не доставлено
    assert len(alerts.sent) == 1
    deliver = True
    await run_at(client, at(37), "docling")
    await run_at(client, at(38), "docling")
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == ["⚠️ Сломано", "✅ Восстановлено"]
    async with sessions() as session:
        (row,) = (await session.scalars(select(ExternalCauseAlert))).all()
    assert row.recovery_alerted_at is not None


async def test_quiet_close_never_sends_a_restored_message(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    """Сбой оповещён, затем сервис выключили вручную: запись закрыта молча, без «восстановлено»."""
    gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))
    await run_at(client, at(0), "docling")
    await run_at(client, at(20), "docling")
    assert len(alerts.sent) == 1
    container = client.app.state.container  # type: ignore[attr-defined]
    async with sessions() as session, session.begin():
        session.add(ExternalServiceSwitch(service_key="docling", disabled=True))
    container.switch_board.invalidate()
    container.external_view.invalidate()
    await container.external_checks._notify(at(25))
    await container.external_checks._notify(at(26))
    assert len(alerts.sent) == 1
    async with sessions() as session:
        (row,) = (await session.scalars(select(ExternalCauseAlert))).all()
    assert row.ended_at is not None


async def test_service_off_for_days_then_fail_alerts_only_fifteen_minutes_after_the_fall(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    """off несколько дней → fail: «с …» и 15 минут — от падения, а не «уже 3 дн»."""
    async with sessions() as session, session.begin():
        for minutes in (-4000, -2000, -10):
            session.add(
                ExternalServiceCheck(
                    service_key="docling",
                    checked_at=at(minutes),
                    tier="cheap",
                    status="off",
                    summary="Не используется",
                )
            )
    gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))
    await run_at(client, at(0), "docling")
    await run_at(client, at(14), "docling")
    assert alerts.sent == []
    await run_at(client, at(16), "docling")
    assert [key for key, _ in alerts.sent] == ["docling:server_down"]
    text = alerts.sent[0][1].plain
    assert "уже 16 мин" in text
    assert " дн" not in text
    container = client.app.state.container  # type: ignore[attr-defined]
    body = (await container.external_view.list(at(16))).model_dump(mode="json")
    service = {s["key"]: s for s in body["services"]}["docling"]
    assert service["since"] == at(0).isoformat().replace("+00:00", "Z")


async def test_groups_name_the_cause_the_owner_and_the_action(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
) -> None:
    auth = await headers(sessions, client, "admin")
    gateway.get(docling).mock(side_effect=httpx.ConnectError("refused"))
    # непрерывный fail дольше 15 минут: первая проверка 20 минут назад, последняя — сейчас
    now = datetime.now(UTC)
    await run_at(client, now - timedelta(minutes=20), "docling")
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
        checks._collector._d.retry_delay_s = 0.0
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
    # затухание 1, 2, 5, 7: проверки на 0-й, 1-й, 3-й, 8-й, 15-й и 22-й минутах полосы сбоя
    seconds = {0: 1, 30: 1, 60: 2, 120: 2, 180: 3, 300: 3, 480: 4, 840: 4, 900: 5, 1200: 5, 1320: 6}
    # (момент в секундах от T0) -> сколько проверок docling должно быть записано к этому моменту
    for sec, expected in seconds.items():
        await container.external_checks.run("cheap", T0 + timedelta(seconds=sec))
        assert len(await docling_checks(sessions)) == expected, sec
    async with sessions() as session:  # на 15-й минуте непрерывного сбоя открылся инцидент
        stmt = select(ExternalServiceIncident).where(
            ExternalServiceIncident.service_key == "docling"
        )
        (opened,) = (await session.scalars(stmt)).all()
    assert (opened.started_at, opened.ended_at) == (T0, None)

    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    await container.external_checks.run("cheap", T0 + timedelta(seconds=1740))  # срок 7 минут
    assert len(await docling_checks(sessions)) == 7
    await container.external_checks.run("cheap", T0 + timedelta(seconds=1800))
    assert len(await docling_checks(sessions)) == 8  # исправное — снова каждую минуту
    await container.external_checks.run("cheap", T0 + timedelta(seconds=2100))  # ok уже 6 минут
    async with sessions() as session:
        (incident,) = (await session.scalars(stmt)).all()
    assert incident.ended_at == T0 + timedelta(seconds=1740)  # строка снялась сама


async def test_recovering_heavy_only_service_is_checked_every_minute_until_restored(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    container = client.app.state.container  # type: ignore[attr-defined]
    async with sessions() as session, session.begin():
        session.add(ExternalServiceIncident(service_key="tls.crm", started_at=T0, summary="x"))
        session.add(
            ExternalServiceCheck(
                service_key="tls.crm",
                checked_at=T0 + timedelta(minutes=20),
                tier="heavy",
                status="ok",
                summary="ok",
            )
        )
    assert (
        await container.external_checks.recheck_broken(T0 + timedelta(minutes=20, seconds=30)) == []
    )
    results = await container.external_checks.recheck_broken(T0 + timedelta(minutes=21))
    assert [r.key for r in results] == ["tls.crm"]  # не ждём 15-минутного прохода


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
    # fail идёт 20 минут (подменённое время), затем проверка «сейчас»: «Сломано» и одно оповещение
    with capture_logs() as logs:
        await run_at(webhook_client, datetime.now(UTC) - timedelta(minutes=20), "telegram")
        await run_at(webhook_client, datetime.now(UTC) - timedelta(minutes=2), "telegram")
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
    assert info.call_count >= 1
    # «Сломано» дольше 15 минут: одно оповещение, без токена и сырого ответа
    assert [k for k, _ in alerts.sent] == ["telegram:webhook_config"]
    assert alerts.sent[0][1].subject.startswith("⚠️ Сломано: Вебхук Telegram не настроен")
    assert "хостинг" in alerts.sent[0][1].plain

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

    await run_at(client, at(0), "erp.litellm")
    await run_at(client, at(10), "erp.litellm")  # короче 15 минут подряд — ни инцидента, ни письма
    assert alerts.sent == []
    async with sessions() as session:
        assert (await session.scalars(select(ExternalServiceIncident))).all() == []

    await run_at(client, at(16), "erp.litellm")
    await run_at(client, at(30), "erp.litellm")  # повтор — тот же инцидент и то же оповещение
    assert [k for k, _ in alerts.sent] == ["erp.litellm:erp_external"]
    broken = alerts.sent[0][1]
    assert (
        broken.subject
        == "⚠️ Сломано: ERP не получает ответы моделей — разбор запросов и черновики КП недоступны"
    )
    assert "Кто исправляет: владелец компании" in broken.plain
    assert "AI_GATEWAY_UNAVAILABLE" not in broken.plain  # сырой текст в оповещение не идёт
    async with sessions() as session:
        (incident,) = (await session.scalars(select(ExternalServiceIncident))).all()
    assert (incident.started_at, incident.ended_at) == (at(0), None)

    connector.facts = erp_facts(erp_item("litellm"))
    await run_at(client, at(40), "erp.litellm")
    await run_at(client, at(46), "erp.litellm")  # ok уже 6 минут
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == ["⚠️ Сломано", "✅ Восстановлено"]
    async with sessions() as session:
        (incident,) = (await session.scalars(select(ExternalServiceIncident))).all()
    assert incident.ended_at == at(40)  # «восстановлено в …» — начало непрерывного ok


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


# --- дребезг: ложные «Сбой/Восстановлено» из-за медленных ответов (прод, W15-H3) -----------------


async def test_a_slow_answer_is_retried_inside_the_check_before_it_counts_as_fail(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
) -> None:
    route = gateway.get(docling).mock(
        side_effect=[httpx.ConnectTimeout("slow"), httpx.Response(200, json={"status": "ok"})]
    )
    await run_at(client, at(0), "docling")
    assert route.call_count == 2
    async with sessions() as session:
        (row,) = (await session.scalars(select(ExternalServiceCheck))).all()
    assert row.status == "ok"  # один медленный ответ — не провал


async def test_two_failed_attempts_are_a_fail(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
) -> None:
    route = gateway.get(docling).mock(side_effect=httpx.ConnectTimeout("slow"))
    await run_at(client, at(0), "docling")
    assert route.call_count == 2
    async with sessions() as session:
        (row,) = (await session.scalars(select(ExternalServiceCheck))).all()
    assert row.status == "fail"


async def test_flapping_every_fifth_check_never_alerts_or_opens_an_incident(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    """Каждая 5-я проверка падает, следующая проходит: ни «Сбоя», ни инцидента — «Нестабильно»."""
    route = gateway.get(docling)
    for minute in range(0, 90):
        if minute % 5 == 0:
            route.mock(side_effect=httpx.ConnectError("slow"))
        else:
            route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
        await run_at(client, at(minute), "docling")
    assert alerts.sent == []
    async with sessions() as session:
        assert (await session.scalars(select(ExternalServiceIncident))).all() == []
        assert (await session.scalars(select(ExternalCauseAlert))).all() == []
    container = client.app.state.container  # type: ignore[attr-defined]
    body = (await container.external_view.list(at(89))).model_dump(mode="json")
    service = {s["key"]: s for s in body["services"]}["docling"]
    assert service["state"] == "unstable"
    assert service["flaps_24h"] >= 3
    (group,) = [g for g in body["groups"] if g["id"] == "docling:flapping"]
    assert group["state"] == "unstable"
    assert "нестабильная связь" in group["headline"]
    assert body["summary"]["fail"] == 0


async def test_repeated_outages_give_one_broken_one_restored_per_day(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    route = gateway.get(docling)

    async def outage(start: int) -> None:
        route.mock(side_effect=httpx.ConnectError("down"))
        for minute in (0, 10, 16, 20):
            await run_at(client, at(start + minute), "docling")
        route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
        for minute in (21, 30, 40):
            await run_at(client, at(start + minute), "docling")

    await outage(0)
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == ["⚠️ Сломано", "✅ Восстановлено"]
    await outage(100)  # те же сутки: ни «Сломано», ни «Восстановлено»
    await outage(200)
    assert len(alerts.sent) == 2
    async with sessions() as session:
        rows = (
            await session.scalars(select(ExternalCauseAlert).order_by(ExternalCauseAlert.id))
        ).all()
    assert [(r.alerted_at is not None, r.suppressed_at is not None) for r in rows] == [
        (True, False),
        (False, True),
        (False, True),
    ]
    # через сутки — снова одно «Сломано»; в нём счёт провалов за сутки
    await outage(1600)
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == [
        "⚠️ Сломано",
        "✅ Восстановлено",
        "⚠️ Сломано",
        "✅ Восстановлено",
    ]


async def test_suppressed_long_outage_is_announced_once_after_the_day_with_the_count(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    """«Сломано» 10:00, «Восстановлено» 10:40, новый сбой 11:00 на двое суток — одно «Сломано» через
    сутки после первого (со сводкой N) и одно «Восстановлено» по окончании."""
    route = gateway.get(docling)
    route.mock(side_effect=httpx.ConnectError("down"))
    for minute in (0, 8, 16):
        await run_at(client, at(minute), "docling")  # «Сломано» в 16-й минуте
    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    for minute in (20, 26, 40):
        await run_at(client, at(minute), "docling")  # «Восстановлено»
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == ["⚠️ Сломано", "✅ Восстановлено"]

    route.mock(side_effect=httpx.ConnectError("down"))
    for minute in (60, 68, 76, 400, 1000, 1440):  # те же сутки: подавлено, сообщения нет
        await run_at(client, at(minute), "docling")
    assert len(alerts.sent) == 2
    async with sessions() as session:
        rows = (
            await session.scalars(select(ExternalCauseAlert).order_by(ExternalCauseAlert.id))
        ).all()
    assert [(r.alerted_at is not None, r.suppressed_at is not None) for r in rows] == [
        (True, False),
        (False, True),
    ]

    await run_at(client, at(1460), "docling")  # сутки с «Сломано» (16-я минута) прошли, сбой идёт
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == [
        "⚠️ Сломано",
        "✅ Восстановлено",
        "⚠️ Сломано",
    ]
    summary = alerts.sent[2][1].plain
    assert "Нестабилен: 2 провала с прошлого сообщения" in summary
    for minute in (2000, 2900):  # дальше сбой идёт двое суток — повторов нет
        await run_at(client, at(minute), "docling")
    assert len(alerts.sent) == 3

    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    for minute in (3000, 3004, 3010):
        await run_at(client, at(minute), "docling")
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == [
        "⚠️ Сломано",
        "✅ Восстановлено",
        "⚠️ Сломано",
        "✅ Восстановлено",
    ]


async def test_a_short_blip_after_recovery_does_not_delay_the_restored_message(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    gateway: respx.MockRouter,
    docling: str,
    alerts: FakeAlerts,
) -> None:
    route = gateway.get(docling)
    route.mock(side_effect=httpx.ConnectError("down"))
    for minute in (0, 8, 16):
        await run_at(client, at(minute), "docling")
    for minute, ok in ((21, True), (22, True), (23, False), (24, True), (26, True)):
        if ok:
            route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
        else:
            route.mock(side_effect=httpx.ConnectError("blip"))
        await run_at(client, at(minute), "docling")
    # ok с 21-й минуты; провал на 23-й между двумя ok отсчёт не сбросил: на 26-й — «Восстановлено»
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == ["⚠️ Сломано", "✅ Восстановлено"]

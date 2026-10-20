"""Центр внешних сервисов (M3-CRM-12, ADR-0024) на реальном Postgres: API, роли, проверка сейчас,
инциденты и оповещения с антиспамом, выключатели (пароль, аудит, LiteLLM через respx), сводка на
«Состоянии системы». Внешние сервисы — подставные (respx), платных вызовов нет."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.external_incidents import AlertText
from app.main import create_app
from app.models.auth import AuditLog, User
from app.models.email import EmailLog
from app.models.external_services import ExternalServiceIncident, ExternalServiceSwitch
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
    assert "Ещё не проверялся" in services["telegram"]["summary"]
    erp = services["erp.cbu_rates"]
    assert (erp["status"], erp["source"], erp["switch"]) == ("unknown", "erp", None)
    assert services["vendor.gemini"]["switch"]["available"] is False  # вендор запасной модели
    assert services["vendor.anthropic"]["switch"]["available"] is True
    assert body["checked_at"] is None
    assert client.get(f"{URL}/nope", headers=auth).status_code == 404


async def test_check_now_opens_and_closes_incident_with_one_alert_each(
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
    # Повторный сбой — тот же инцидент, без второго оповещения.
    client.post(f"{URL}/docling/check", headers=auth)
    assert [k for k, _ in alerts.sent] == ["docling"]
    assert alerts.sent[0][1].subject.startswith("⚠️ Сбой:")

    route.mock(return_value=httpx.Response(200, json={"status": "ok"}))
    recovered = client.post(f"{URL}/docling/check", headers=auth).json()
    assert recovered["service"]["status"] == "ok"
    assert recovered["service"]["incident"] is None
    (incident,) = recovered["incidents"]
    assert incident["ended_at"] is not None
    assert incident["alerted"]
    assert incident["recovery_alerted"]
    assert [a.subject.split(":")[0] for _, a in alerts.sent] == ["⚠️ Сбой", "✅ Восстановлено"]
    assert recovered["service"]["uptime_24h"] == pytest.approx(1 / 3, abs=0.01)

    # Новый сбой в пределах часа — инцидент записан, но без оповещения (антиспам).
    route.mock(side_effect=httpx.ConnectError("refused"))
    client.post(f"{URL}/docling/check", headers=auth)
    assert len(alerts.sent) == 2
    async with sessions() as session:
        rows = (await session.scalars(select(ExternalServiceIncident))).all()
    assert len(rows) == 2
    assert sum(r.alerted_at is not None for r in rows) == 1


async def test_background_pass_records_all_crm_services(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await headers(sessions, client, "admin")
    container = client.app.state.container  # type: ignore[attr-defined]
    results = await container.external_checks.run("cheap", datetime.now(UTC))
    keys = {r.key for r in results}
    assert {"telegram", "litellm", "langfuse", "mail", "s3", "docling", "backup"} <= keys
    assert not any(k.startswith(("tls.", "erp.")) for k in keys)
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
    assert [k for k, _ in alerts.sent] == ["erp_sync"]

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
    assert [k for k, _ in alerts.sent] == ["erp_handoff"]

    async with sessions() as session, session.begin():
        saved = await session.get(Client, client_id)
        assert saved is not None
        saved.erp_handoff_status, saved.erp_handoff_error = "done", None
    healed = client.post(f"{URL}/erp_handoff/check", headers=auth).json()["service"]
    assert healed["status"] == "off"


async def test_erp_events_rejections_land_in_the_feed_and_heal_when_old(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, alerts: FakeAlerts
) -> None:
    """FIX-33: отклонённое событие (чужая компания, неизвестный тип) — сбой строки «События ERP»."""
    from app.models.integrations import ErpIncomingEvent

    auth = await headers(sessions, client, "admin")
    quiet = client.post(f"{URL}/erp_events/check", headers=auth).json()["service"]
    assert (quiet["status"], quiet["key"]) == ("ok", "erp_events")

    async with sessions() as session, session.begin():
        session.add(
            ErpIncomingEvent(
                event_id="00000000-0000-4000-8000-000000000001",
                event_type="quote.sent",
                erp_company_id=7,
                crm_client_id=1,
                payload={},
                status="rejected",
                error="company mismatch: client #1 is erp company #5, event carries #7",
            )
        )
    failed = client.post(f"{URL}/erp_events/check", headers=auth).json()["service"]
    assert failed["status"] == "fail"
    assert "company mismatch" in failed["error"]
    assert failed["hint"]
    assert [k for k, _ in alerts.sent] == ["erp_events"]

    async with sessions() as session, session.begin():  # разобрано давно: в окно недели не входит
        row = await session.get(ErpIncomingEvent, "00000000-0000-4000-8000-000000000001")
        assert row is not None
        row.received_at = datetime.now(UTC) - timedelta(days=30)
    healed = client.post(f"{URL}/erp_events/check", headers=auth).json()["service"]
    assert healed["status"] == "ok"

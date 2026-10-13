"""Коннектор «Почта» (M3-CRM-08) на реальном Postgres: роли, секреты, журнал `email_log`,
приглашение без SMTP (409 и `skipped_no_smtp`, пароль цел) и с SMTP (письмо через очередь)."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.integrations.smtp import SmtpCheck, SmtpConnection, SmtpProbeError
from app.main import create_app
from app.models.auth import AuditLog
from app.models.email import EmailLog
from app.models.integrations import IntegrationSecret
from app.security.secrets_store import SecretCipher
from app.services.mail import MailService
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration

URL = "/api/v1/integrations/smtp"
RELAY_PASSWORD = "integration-relay-password-Ab12"  # фиктивный, в сеть не уходит
SECRETS_KEY = "k" * 64


class FakeTransport:
    def __init__(self) -> None:
        self.error: SmtpProbeError | None = None
        self.sent: list[tuple[str, str, str]] = []
        self.checked: list[SmtpConnection] = []

    async def check(self, connection: SmtpConnection) -> SmtpCheck:
        self.checked.append(connection)
        if self.error is not None:
            raise self.error
        return SmtpCheck("relay.test ESMTP", bool(connection.username), 3)

    async def send(self, connection: SmtpConnection, to: str, subject: str, body: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((to, subject, body))


class Harness:
    def __init__(self) -> None:
        self.transport = FakeTransport()
        self.queued: list[int] = []


@pytest.fixture
def harness() -> Harness:
    return Harness()


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings, harness: Harness
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr(SECRETS_KEY)})
    app = create_app(settings)
    with TestClient(app) as test_client:
        container = app.state.container

        async def enqueue(email_log_id: int) -> int:
            harness.queued.append(email_log_id)
            return email_log_id

        container.__dict__["mail_service"] = MailService(
            container.session_factory,
            container.secrets_store,
            SecretCipher(SECRETS_KEY),
            settings,
            container.settings_service,
            harness.transport,
            enqueue,
        )
        yield test_client


async def headers(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> dict[str, str]:
    account, password = await make_user(sessions, f"{role}@railtech.uz", [role])
    return login(client, account.email, password)


def connector_body(**extra: Any) -> dict[str, Any]:
    return {
        "host": "smtp.test",
        "port": 587,
        "security": "starttls",
        "from_email": "crm@railtech.test",
        "from_name": "RailTech CRM",
        "username": "crm",
        "smtp_password": RELAY_PASSWORD,
        "password": PASSWORD,
        **extra,
    }


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_non_admin_forbidden(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> None:
    auth = await headers(sessions, client, role)
    assert client.get(URL, headers=auth).status_code == 403
    assert client.put(URL, json=connector_body(), headers=auth).status_code == 403
    assert client.post(f"{URL}/check", headers=auth).status_code == 403
    assert client.post(f"{URL}/test-send", headers=auth).status_code == 403
    assert client.get(f"{URL}/log", headers=auth).status_code == 403


async def test_anonymous_unauthorized(client: TestClient) -> None:
    assert client.get(URL).status_code == 401
    assert client.get(f"{URL}/log").status_code == 401


async def test_invite_without_smtp_is_clear_error_and_password_survives(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, harness: Harness
) -> None:
    auth = await headers(sessions, client, "admin")
    status = client.get(URL, headers=auth).json()
    assert (status["configured"], status["settings_source"]) == (False, "none")
    assert client.post(f"{URL}/check", headers=auth).json()["details"]["reason"] == (
        "smtp_not_configured"
    )

    manager, manager_password = await make_user(sessions, "m@railtech.uz", ["manager"])
    invite = client.post(f"/api/v1/users/{manager.id}/invite", headers=auth)
    assert invite.status_code == 409, invite.text
    assert invite.json()["details"]["reason"] == "smtp_not_configured"
    # Пароль не менялся: менеджер входит прежним (Q-010 остаётся рабочим путём).
    login(client, manager.email, manager_password)
    assert harness.queued == []
    # Тестовое письмо без коннектора — тоже 409, но строка журнала `skipped_no_smtp` появляется.
    test_send = client.post(f"{URL}/test-send", headers=auth)
    assert test_send.status_code == 409
    log = client.get(f"{URL}/log", headers=auth).json()
    assert [row["status"] for row in log] == ["skipped_no_smtp"]
    assert log[0]["to_email"] == "admin@railtech.uz"
    assert client.get(f"{URL}/log?status=sent", headers=auth).json() == []


async def test_connector_saved_checked_and_letters_flow_through_journal(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, harness: Harness
) -> None:
    auth = await headers(sessions, client, "admin")
    wrong = client.put(URL, json=connector_body(password="nope"), headers=auth)
    assert wrong.json()["details"]["reason"] == "wrong_password"
    bad_host = client.put(URL, json=connector_body(host="smtp.test:587"), headers=auth)
    assert bad_host.status_code == 422
    assert bad_host.json()["details"] == {"reason": "smtp_invalid_host", "field": "host"}

    saved = client.put(URL, json=connector_body(), headers=auth)
    assert saved.status_code == 200, saved.text
    status = saved.json()
    assert (status["configured"], status["host"], status["settings_source"]) == (
        True,
        "smtp.test",
        "db",
    )
    assert (status["username"], status["password_last4"], status["password_source"]) == (
        "crm",
        "Ab12",
        "db",
    )
    assert RELAY_PASSWORD not in saved.text

    checked = client.post(f"{URL}/check", headers=auth)
    assert checked.status_code == 200, checked.text
    assert checked.json() == {"server": "relay.test ESMTP", "authenticated": True, "latency_ms": 3}
    assert harness.transport.checked[0].password == RELAY_PASSWORD

    harness.transport.error = SmtpProbeError("auth_failed", "SMTP 535")
    rejected = client.post(f"{URL}/check", headers=auth)
    assert rejected.status_code == 502
    assert rejected.json()["details"]["reason"] == "smtp_auth_failed"
    harness.transport.error = None

    # Приглашение: пароль сменён, письмо в очереди; доставка воркером → `sent`, тело стёрто.
    manager, old_password = await make_user(sessions, "m@railtech.uz", ["manager"])
    invite = client.post(f"/api/v1/users/{manager.id}/invite", headers=auth)
    assert invite.status_code == 200, invite.text
    assert invite.json()["status"] == "queued"
    email_log_id = invite.json()["email_log_id"]
    assert harness.queued == [email_log_id]
    old_login = client.post(
        "/api/v1/auth/login", json={"email": manager.email, "password": old_password}
    )
    assert old_login.status_code == 401

    container = client.app.state.container  # type: ignore[attr-defined]
    assert await container.mail_service.deliver(email_log_id) is True
    (to, subject, body) = harness.transport.sent[0]
    assert to == "m@railtech.uz"
    assert "RailTech" in subject
    temporary = body.split("Временный пароль: ")[1].splitlines()[0]
    login(client, manager.email, temporary)  # письмо содержит рабочий временный пароль

    # Сброс по почте и тестовое письмо — тоже в журнале; фильтр по статусу работает.
    reset = client.post(f"/api/v1/users/{manager.id}/reset-password/email", headers=auth)
    assert reset.status_code == 200
    test_send = client.post(f"{URL}/test-send", headers=auth)
    assert test_send.status_code == 200
    log = client.get(f"{URL}/log", headers=auth).json()
    assert [(row["template"], row["status"]) for row in log] == [
        ("test", "queued"),
        ("password_reset", "queued"),
        ("invite", "sent"),
    ]
    assert client.get(f"{URL}/log?status=sent", headers=auth).json()[0]["id"] == email_log_id
    assert all("Временный пароль" not in row["subject"] for row in log)

    async with sessions() as session:
        rows = (await session.execute(select(EmailLog))).scalars().all()
        secrets = (await session.execute(select(IntegrationSecret))).scalars().all()
        audits = (await session.execute(select(AuditLog))).scalars().all()
    sent_row = next(r for r in rows if r.id == email_log_id)
    assert (sent_row.status, sent_row.body_ciphertext, sent_row.attempts) == ("sent", None, 1)
    assert sent_row.sent_at is not None
    assert all(temporary.encode() not in (r.body_ciphertext or b"") for r in rows)
    assert {s.key for s in secrets} >= {"smtp_username", "smtp_password"}
    assert all(RELAY_PASSWORD.encode() not in s.ciphertext for s in secrets)
    actions = [a.action for a in audits]
    assert actions.count("integrations.smtp") == 1
    assert {"user.invite", "user.reset_password_email"} <= set(actions)
    assert all(RELAY_PASSWORD not in repr((a.before, a.after)) for a in audits)
    assert all(temporary not in repr((a.before, a.after)) for a in audits)

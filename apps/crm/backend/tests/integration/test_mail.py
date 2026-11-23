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
from app.domain.errors import ConflictError
from app.domain.password_reset import hash_token
from app.integrations.smtp import SmtpCheck, SmtpConnection, SmtpProbeError
from app.main import create_app
from app.models.auth import AuditLog, PasswordResetToken
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
    settings = live_settings.model_copy(
        update={
            "secrets_key": SecretStr(SECRETS_KEY),
            "platform_public_url": "https://platform.example.com",
        }
    )
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

    # Приглашение: прежний пароль закрыт, письмо со ссылкой в очереди; доставка → `sent`.
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
    # ДВ-7: в письме ссылка «Задайте пароль» на Платформу, пароля нет.
    assert "https://platform.example.com/reset-password?token=" in body
    assert "localhost" not in body
    assert "емпорар" not in body.lower()
    assert "temporary" not in body.lower()
    assert old_password not in body
    temporary = body.split("token=")[1].split()[0]  # токен ссылки: в базе его быть не должно
    new_password = "Fresh-secret-2026-x"
    set_password = client.post(
        "/api/v1/auth/reset-password", json={"token": temporary, "new_password": new_password}
    )
    assert set_password.status_code == 204, set_password.text
    login(client, manager.email, new_password)
    again = client.post(
        "/api/v1/auth/reset-password", json={"token": temporary, "new_password": new_password}
    )
    assert again.status_code == 422  # ссылка одноразовая
    assert again.json()["details"]["reason"] == "reset_token_invalid"

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
    assert all(temporary not in row["subject"] for row in log)

    async with sessions() as session:
        rows = (await session.execute(select(EmailLog))).scalars().all()
        secrets = (await session.execute(select(IntegrationSecret))).scalars().all()
        audits = (await session.execute(select(AuditLog))).scalars().all()
    sent_row = next(r for r in rows if r.id == email_log_id)
    assert (sent_row.status, sent_row.body_ciphertext, sent_row.attempts) == ("sent", None, 1)
    assert sent_row.sent_at is not None
    assert all(temporary.encode() not in (r.body_ciphertext or b"") for r in rows)
    async with sessions() as session:
        stored = (await session.execute(select(PasswordResetToken))).scalars().all()
    assert {t.token_hash for t in stored} >= {hash_token(temporary)}
    assert all(t.token_hash != temporary for t in stored)
    assert {s.key for s in secrets} >= {"smtp_username", "smtp_password"}
    assert all(RELAY_PASSWORD.encode() not in s.ciphertext for s in secrets)
    actions = [a.action for a in audits]
    assert actions.count("integrations.smtp") == 1
    assert {"user.invite", "user.reset_password_email"} <= set(actions)
    assert all(RELAY_PASSWORD not in repr((a.before, a.after)) for a in audits)
    assert all(temporary not in repr((a.before, a.after)) for a in audits)


# --- СЦ-3: письма, не ушедшие без почты, уходят после её подключения ----------------------------


async def _skipped_bus_row(
    sessions: async_sessionmaker[AsyncSession], source: str, purpose: str, key: str
) -> int:
    """Письмо домена по шине, принятое без почты: тело хранится (без секрета)."""
    async with sessions() as session, session.begin():
        row = EmailLog(
            to_email="client@example.test",
            subject="Счёт",
            template=purpose,
            lang="ru",
            status="skipped_no_smtp",
            error="smtp_not_configured",
            attempts=0,
            source=source,
            purpose=purpose,
            request_key=key,
            body_ciphertext=SecretCipher(SECRETS_KEY).encrypt("Текст письма"),
        )
        session.add(row)
        await session.flush()
        return row.id


async def test_missed_letters_go_out_after_mail_is_connected(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, harness: Harness
) -> None:
    from app.services.mail_templates import RenderedEmail

    auth = await headers(sessions, client, "admin")
    container = client.app.state.container  # type: ignore[attr-defined]
    mail: MailService = container.mail_service
    text = RenderedEmail(subject="Ответ клиенту", body="Здравствуйте", lang="ru")

    # Без почты: своё письмо без секрета хранит текст, приглашение со входом — нет.
    with pytest.raises(ConflictError):
        await mail.send_rendered("client_reply", "client@example.test", text)
    with pytest.raises(ConflictError):
        await mail.send_rendered("invite", "staff@example.test", text)
    erp_id = await _skipped_bus_row(sessions, "erp", "invoice_issued", "erp-key-1")
    eds_id = await _skipped_bus_row(sessions, "eds", "letter", "eds-key-1")
    async with sessions() as session:
        rows = {r.template: r for r in (await session.scalars(select(EmailLog))).all()}
    own_id = rows["client_reply"].id
    assert rows["client_reply"].body_ciphertext is not None
    assert rows["invite"].body_ciphertext is None

    before = client.get(URL, headers=auth).json()
    assert before["configured"] is False
    assert before["missed"] == 0, "без почты отправлять нечем — счётчика нет"

    saved = client.put(URL, json=connector_body(), headers=auth)
    assert saved.json()["missed"] == 2, (
        "своё письмо и письмо ERP; EDS и приглашение со входом — нет"
    )

    sent = client.post(f"{URL}/missed", headers=auth)
    assert sent.status_code == 200, sent.text
    assert sent.json() == {"queued": 2}
    assert sorted(harness.queued) == sorted([own_id, erp_id]), "та же строка журнала, не копия"
    assert client.get(URL, headers=auth).json()["missed"] == 0

    async with sessions() as session:
        after = {r.id: r for r in (await session.scalars(select(EmailLog))).all()}
        audits = [a.action for a in (await session.scalars(select(AuditLog))).all()]
    assert (after[erp_id].status, after[erp_id].error, after[erp_id].request_key) == (
        "queued",
        None,
        "erp-key-1",
    )
    assert after[eds_id].status == "skipped_no_smtp", "письма EDS уходят из документа"
    assert "integrations.smtp.missed_sent" in audits

    assert await mail.deliver(erp_id) is True
    async with sessions() as session:
        delivered = await session.get(EmailLog, erp_id)
    assert delivered is not None
    assert delivered.status == "sent"


async def test_missed_letters_wait_while_mail_is_paused(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, harness: Harness
) -> None:
    auth = await headers(sessions, client, "admin")
    container = client.app.state.container  # type: ignore[attr-defined]
    erp_id = await _skipped_bus_row(sessions, "erp", "invoice_issued", "erp-key-2")
    client.put(URL, json=connector_body(), headers=auth)

    async def paused() -> bool:
        return True

    container.mail_service._paused = paused  # пауза почты: строки ждут `resume_queued`
    assert await container.mail_service.send_missed(None) == 1
    assert harness.queued == []
    async with sessions() as session:
        row = await session.get(EmailLog, erp_id)
    assert row is not None
    assert row.status == "queued"

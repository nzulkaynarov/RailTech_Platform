"""«Подключить ERP» и «Обновить ключи» через API (M3-CRM-10) на настоящей БД CRM.

ERP подменена respx. Проверяется по CRM: роли, пароль, секреты в БД зашифрованы и не
возвращаются, после сопряжения вебхуки принимаются по сгенерированному секрету, ротация
принимает оба секрета в переход и снимает предыдущий по сроку, в аудите и журналах нет значений.
"""

import hashlib
import hmac
import json
import logging
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog
from app.models.integrations import IntegrationSecret
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration

BASE = "https://erp.pairing.example"
ERP_URL = "/api/v1/integrations/erp"
CODE = "ABCD-EFGH-JKMN"  # фиктивный код сопряжения
ACCEPT = f"{BASE}/api/integration/v1/pairing/accept"
ROTATE = f"{BASE}/api/integration/v1/pairing/rotate"
HEALTH = f"{BASE}/api/integration/v1/health"
HEALTHY = {
    "status": "ok",
    "version": "test",
    "migrations_applied": True,
    "queue_alive": True,
    "checked_at": "2026-10-21T09:00:00+05:00",
}
ACCEPTED = {"paired": True, "paired_at": "2026-10-21T10:00:00+05:00", "erp_version": "test"}
ROTATED = {
    "rotated": True,
    "rotated_at": "2026-10-21T10:00:00+05:00",
    "previous_token_valid_until": "2026-10-21T11:00:00+05:00",
}


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr("k" * 64)})
    app = create_app(settings)
    with TestClient(app) as test_client:
        app.state.bot = None
        yield test_client


async def admin(sessions: async_sessionmaker[AsyncSession], client: TestClient) -> dict[str, str]:
    account, password = await make_user(sessions, "pairing-admin@railtech.uz", ["admin"])
    return login(client, account.email, password)


def post_event(client: TestClient, secret: str, serial: int) -> int:
    from tests.seam_events import example_event

    body = example_event("quote.viewed")
    body["occurred_at"] = f"2026-10-21T11:{serial:02d}:00+05:00"
    raw = json.dumps(body).encode()
    signature = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post(
        f"{ERP_URL}/events",
        content=raw,
        headers={
            "X-Event-Id": str(uuid.uuid4()),
            "X-Event-Type": "quote.viewed",
            "X-Signature": signature,
            "Content-Type": "application/json",
        },
    ).status_code


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_pairing_is_admin_only(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> None:
    account, password = await make_user(sessions, f"{role}-pair@railtech.uz", [role])
    auth = login(client, account.email, password)
    body = {"base_url": BASE, "code": CODE, "password": PASSWORD}
    assert client.post(f"{ERP_URL}/pair", json=body, headers=auth).status_code == 403
    assert (
        client.post(f"{ERP_URL}/rotate", json={"password": PASSWORD}, headers=auth).status_code
        == 403
    )
    assert client.post(f"{ERP_URL}/pair", json=body).status_code == 401
    assert client.post(f"{ERP_URL}/rotate", json={"password": PASSWORD}).status_code == 401


@respx.mock
async def test_pair_then_rotate_end_to_end(
    sessions: async_sessionmaker[AsyncSession],
    client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    auth = await admin(sessions, client)
    accept = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    health = respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    caplog.set_level(logging.DEBUG)

    wrong = client.post(
        f"{ERP_URL}/pair", json={"base_url": BASE, "code": CODE, "password": "nope"}, headers=auth
    )
    assert wrong.status_code == 422
    assert wrong.json()["details"]["reason"] == "wrong_password"
    assert not accept.called

    paired = client.post(
        f"{ERP_URL}/pair", json={"base_url": BASE, "code": CODE, "password": PASSWORD}, headers=auth
    )
    assert paired.status_code == 200, paired.text
    data = paired.json()
    assert data["check"]["status"] == "ok"
    assert data["check_error"] is None
    status = data["status"]
    assert status["paired"] is True
    assert status["configured"]
    assert status["mode"] == "erp"
    assert (status["base_url"], status["token_source"], status["webhook_secret_source"]) == (
        BASE,
        "db",
        "db",
    )
    assert status["inbound_token_configured"] is True

    sent = json.loads(accept.calls.last.request.content)
    assert accept.calls.last.request.headers["authorization"] == f"Bearer {CODE}"
    first_hook = sent["webhook_secret"]
    assert (
        health.calls.last.request.headers["authorization"] == f"Bearer {sent['crm_to_erp_token']}"
    )
    for secret in (CODE, *sent.values()):
        assert secret not in paired.text

    # Вебхуки сразу принимаются по секрету, который сгенерировала CRM.
    assert post_event(client, first_hook, 1) == 200
    assert post_event(client, "not-the-generated-secret-value-0001", 2) == 401

    # Ключи лежат в БД шифрованно.
    async with sessions() as session:
        rows = {r.key: r for r in (await session.execute(select(IntegrationSecret))).scalars()}
    assert {"erp_service_token", "erp_inbound_token", "erp_webhook_secret"} <= set(rows)
    assert all(
        value.encode() not in row.ciphertext for row in rows.values() for value in sent.values()
    )

    # «Обновить ключи».
    rotate = respx.post(ROTATE).mock(return_value=httpx.Response(200, json=ROTATED))
    rotated = client.post(f"{ERP_URL}/rotate", json={"password": PASSWORD}, headers=auth)
    assert rotated.status_code == 200, rotated.text
    new = json.loads(rotate.calls.last.request.content)
    assert (
        rotate.calls.last.request.headers["authorization"] == f"Bearer {sent['crm_to_erp_token']}"
    )
    assert new["crm_to_erp_token"] != sent["crm_to_erp_token"]
    out = rotated.json()
    assert out["check"]["status"] == "ok"
    assert out["status"]["previous_secret_until"] is not None
    assert out["status"]["webhook_secret_previous_configured"] is True
    assert health.calls.last.request.headers["authorization"] == f"Bearer {new['crm_to_erp_token']}"
    assert post_event(client, first_hook, 3) == 200, "в переход принимается и прежний секрет"
    assert post_event(client, new["webhook_secret"], 4) == 200

    # Срок перехода вышел — прежний секрет снимает сама CRM при ближайшей проверке связи.
    async with sessions() as session:
        from app.models.leads import Setting

        row = await session.get(Setting, "integrations")
        assert row is not None
        value = dict(row.value)
        value["erp_previous_secret_until"] = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
        row.value = value
        await session.commit()
    client.app.state.container.settings_service.invalidate()  # type: ignore[attr-defined]
    checked = client.post(f"{ERP_URL}/check", headers=auth)
    assert checked.status_code == 200, checked.text
    assert post_event(client, first_hook, 5) == 401, "прежний секрет снят"
    assert post_event(client, new["webhook_secret"], 6) == 200
    assert client.get(ERP_URL, headers=auth).json()["webhook_secret_previous_configured"] is False

    # Нигде нет значений: ни в аудите, ни в логах.
    secrets_ = (CODE, *sent.values(), *new.values())
    async with sessions() as session:
        audits = (await session.execute(select(AuditLog))).scalars().all()
    actions = {a.action for a in audits}
    assert {"integrations.erp.pair", "integrations.erp.rotate"} <= actions
    dump = repr([(a.before, a.after) for a in audits]) + caplog.text + rotated.text
    for secret in secrets_:
        assert secret not in dump


@respx.mock
async def test_pair_with_rejected_code_leaves_connector_untouched(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await admin(sessions, client)
    respx.post(ACCEPT).mock(
        return_value=httpx.Response(401, json={"detail": "PAIRING_CODE_EXPIRED"})
    )
    failed = client.post(
        f"{ERP_URL}/pair", json={"base_url": BASE, "code": CODE, "password": PASSWORD}, headers=auth
    )
    assert failed.status_code == 422
    assert failed.json()["details"] == {"reason": "erp_pairing_code_expired", "field": "code"}
    status = client.get(ERP_URL, headers=auth).json()
    assert (status["configured"], status["paired"], status["mode"]) == (False, False, "local")
    async with sessions() as session:
        assert (await session.execute(select(IntegrationSecret))).first() is None


@respx.mock
async def test_rotate_without_connector_is_conflict_and_failed_rotation_keeps_secrets(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> None:
    auth = await admin(sessions, client)
    not_configured = client.post(f"{ERP_URL}/rotate", json={"password": PASSWORD}, headers=auth)
    assert not_configured.status_code == 409
    assert not_configured.json()["details"]["reason"] == "erp_not_configured"

    accept = respx.post(ACCEPT).mock(return_value=httpx.Response(200, json=ACCEPTED))
    respx.get(HEALTH).mock(return_value=httpx.Response(200, json=HEALTHY))
    paired = client.post(
        f"{ERP_URL}/pair", json={"base_url": BASE, "code": CODE, "password": PASSWORD}, headers=auth
    )
    hook = json.loads(accept.calls.last.request.content)["webhook_secret"]
    assert paired.status_code == 200
    respx.post(ROTATE).mock(return_value=httpx.Response(500))
    failed = client.post(f"{ERP_URL}/rotate", json={"password": PASSWORD}, headers=auth)
    assert failed.status_code == 502
    assert post_event(client, hook, 1) == 200, "секрет вебхуков откатился на прежний"
    status = client.get(ERP_URL, headers=auth).json()
    assert status["webhook_secret_previous_configured"] is False
    assert status["previous_secret_until"] is None

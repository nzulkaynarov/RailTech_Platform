"""Внешняя копия в интерфейсе (OPS-GDRIVE-2): права, ключ только на запись, доставка, проверка."""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain import gdrive
from app.main import create_app
from app.models.auth import AuditLog
from app.models.integrations import IntegrationSecret
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.security.reauth import LockoutPolicy
from app.services.offsite_connector import OffsiteConnectorService
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration

URL = "/api/v1/integrations/offsite"
FOLDER = "0AbCdEfGhIjKlMnOpQrStUvWxYz"
PRIVATE = "-----BEGIN PRIVATE KEY-----\nMIIEfakefakefakeSECRETBODY\n-----END PRIVATE KEY-----\n"
KEY = json.dumps(
    {
        "type": "service_account",
        "private_key_id": "0123456789abcdef0123456789abcdef1a2b",
        "private_key": PRIVATE,
        "client_email": "rt-offsite-backup@rt-backups.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
)


@dataclass
class FakeStorage:
    """Бакет offsite-config: что CRM туда положила (у неё там только запись)."""

    objects: dict[tuple[str, str], bytes] = field(default_factory=dict)
    fail: bool = False

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        if self.fail:
            raise ConnectionError("rustfs down")
        self.objects[(bucket, key)] = data


@dataclass
class FakeProbe:
    reason: gdrive.ProbeReason = "ok"
    seen: list[tuple[str, str]] = field(default_factory=list)

    async def __call__(self, key: gdrive.ServiceAccountKey, folder: str) -> gdrive.ProbeResult:
        self.seen.append((key.client_email, folder))
        return gdrive.ProbeResult(
            self.reason, "rt-platform-offsite" if self.reason == "ok" else None
        )


@dataclass
class Harness:
    client: TestClient
    storage: FakeStorage
    probe: FakeProbe


@pytest.fixture
def harness(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[Harness]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr("k" * 64)})
    app = create_app(settings)
    with TestClient(app) as client:
        container = app.state.container
        storage, probe = FakeStorage(), FakeProbe()
        container.offsite_connector = OffsiteConnectorService(
            container.session_factory,
            container.settings_service,
            container.secrets_store,
            storage,
            "offsite-config",
            probe,
            lockout=LockoutPolicy(10, 15),
        )
        yield Harness(client, storage, probe)


async def headers(
    sessions: async_sessionmaker[AsyncSession], client: TestClient, role: str
) -> dict[str, str]:
    account, password = await make_user(sessions, f"{role}@railtech.uz", [role])
    return login(client, account.email, password)


def body(**fields: object) -> dict[str, object]:
    out: dict[str, object] = {"key_json": KEY, "folder_id": FOLDER, "password": PASSWORD}
    out.update(fields)
    return out


@pytest.mark.parametrize("role", ["manager", "viewer"])
async def test_only_admin_reads_and_writes(
    sessions: async_sessionmaker[AsyncSession], harness: Harness, role: str
) -> None:
    auth = await headers(sessions, harness.client, role)
    assert harness.client.get(URL, headers=auth).status_code == 403
    assert harness.client.put(URL, json=body(), headers=auth).status_code == 403
    assert harness.client.post(f"{URL}/check", headers=auth).status_code == 403
    assert harness.storage.objects == {}


async def test_director_with_admin_read_sees_but_cannot_change_or_check(
    sessions: async_sessionmaker[AsyncSession], harness: Harness
) -> None:
    """«Директор» (раздел admin — чтение): видит состояние, но не меняет и не проверяет."""
    account, _ = await make_user(sessions, "director@railtech.uz", ["viewer"])
    async with sessions() as session:
        ids = [r.id for r in await prepo.by_codes(session, ["DIRECTOR"])]
    await UserService(sessions).update(Actor.system(), account.id, UserPatch(platform_role_ids=ids))
    auth = login(harness.client, account.email, PASSWORD)
    assert harness.client.get(URL, headers=auth).status_code == 200
    assert harness.client.put(URL, json=body(), headers=auth).status_code == 403
    assert harness.client.post(f"{URL}/check", headers=auth).status_code == 403
    assert harness.storage.objects == {}


async def test_key_with_a_foreign_token_uri_is_rejected_before_anything_leaves(
    sessions: async_sessionmaker[AsyncSession], harness: Harness
) -> None:
    """SSRF: ключ с чужим token_uri не принимается — ни доставки, ни проверки у «Google»."""
    auth = await headers(sessions, harness.client, "admin")
    evil = json.loads(KEY) | {"token_uri": "https://evil.example/token"}
    rejected = harness.client.put(URL, json=body(key_json=json.dumps(evil)), headers=auth)
    assert rejected.status_code == 422
    assert rejected.json()["details"]["problem"] == "foreign_token_uri"
    assert harness.storage.objects == {}
    assert harness.probe.seen == []


async def test_key_is_write_only_delivered_to_the_copy_service_and_checked(
    sessions: async_sessionmaker[AsyncSession], harness: Harness
) -> None:
    client = harness.client
    auth = await headers(sessions, client, "admin")
    empty = client.get(URL, headers=auth).json()
    assert (empty["configured"], empty["key_suffix"], empty["last_check"]) == (False, None, None)
    assert client.post(f"{URL}/check", headers=auth).json()["details"]["reason"] == (
        "offsite_not_configured"
    )

    wrong = client.put(URL, json=body(password="nope"), headers=auth)
    assert wrong.json()["details"]["reason"] == "wrong_password"
    not_key = client.put(URL, json=body(key_json='{"type": "authorized_user"}'), headers=auth)
    assert not_key.status_code == 422
    assert not_key.json()["details"] == {
        "reason": "offsite_key_invalid",
        "field": "key_json",
        "problem": "not_service_account",
    }
    bad_folder = client.put(URL, json=body(folder_id="папка"), headers=auth)
    assert bad_folder.json()["details"] == {
        "reason": "offsite_folder_invalid",
        "field": "folder_id",
    }
    assert harness.storage.objects == {}  # ничего не доставлено, пока ввод не проверен

    saved = client.put(
        URL,
        json=body(folder_id=f"https://drive.google.com/drive/folders/{FOLDER}?usp=sharing"),
        headers=auth,
    )
    assert saved.status_code == 200, saved.text
    status = saved.json()
    assert status["configured"] is True
    assert status["folder_id"] == FOLDER
    assert status["client_email"] == "rt-offsite-backup@rt-backups.iam.gserviceaccount.com"
    assert status["key_suffix"] == "1a2b"
    assert status["delivered_at"] is not None
    assert status["last_check"]["reason"] == "ok"
    assert status["last_check"]["folder_name"] == "rt-platform-offsite"
    # Ключ не возвращается ни в ответе сохранения, ни в GET.
    for text in (saved.text, client.get(URL, headers=auth).text):
        assert "SECRETBODY" not in text
        assert "private_key" not in text
    # Доставка сервису копирования: ключ и папка в бакете offsite-config, ровно как загружены.
    assert harness.storage.objects[("offsite-config", "gdrive-sa.json")] == KEY.encode()
    assert json.loads(harness.storage.objects[("offsite-config", "settings.json")]) == {
        "folder_id": FOLDER
    }

    # Сменить только папку: ключ прежний, доставляется снова; проверка — с тем же аккаунтом.
    harness.probe.reason = "not_shared_drive"
    other = "1ZyXwVuTsRqPoNmLkJiHgFeDcBa"
    moved = client.put(URL, json=body(key_json=None, folder_id=other), headers=auth)
    assert moved.status_code == 200, moved.text
    assert (moved.json()["folder_id"], moved.json()["last_check"]["reason"]) == (
        other,
        "not_shared_drive",
    )
    assert harness.probe.seen[-1] == ("rt-offsite-backup@rt-backups.iam.gserviceaccount.com", other)
    checked = client.post(f"{URL}/check", headers=auth)
    assert (checked.status_code, checked.json()["ok"], checked.json()["reason"]) == (
        200,
        False,
        "not_shared_drive",
    )

    async with sessions() as session:
        secret = await session.get(IntegrationSecret, "offsite_gdrive_key")
        audits = (await session.execute(select(AuditLog))).scalars().all()
    assert secret is not None
    assert b"SECRETBODY" not in secret.ciphertext
    offsite = [a for a in audits if a.action == "integrations.offsite_gdrive"]
    assert len(offsite) == 2
    after = [a.after or {} for a in offsite]
    assert after[0]["key_suffix"] == "1a2b"
    assert after[0]["key_changed"] is True
    assert after[1]["key_changed"] is False
    assert all("SECRETBODY" not in repr((a.before, a.after)) for a in audits)


async def test_failed_delivery_saves_nothing(
    sessions: async_sessionmaker[AsyncSession], harness: Harness
) -> None:
    auth = await headers(sessions, harness.client, "admin")
    harness.storage.fail = True
    failed = harness.client.put(URL, json=body(), headers=auth)
    assert failed.status_code == 502
    assert failed.json()["details"]["reason"] == "offsite_delivery_failed"
    assert harness.client.get(URL, headers=auth).json()["configured"] is False
    async with sessions() as session:
        assert await session.get(IntegrationSecret, "offsite_gdrive_key") is None

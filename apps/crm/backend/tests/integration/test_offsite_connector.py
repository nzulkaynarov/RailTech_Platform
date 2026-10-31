"""Внешняя копия в интерфейсе (OPS-GDRIVE-2, OPS-YADISK): права, провайдер, секрет только на запись,
доставка, проверка."""

import json
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain import gdrive, yadisk
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
class FakeYandexProbe:
    reason: yadisk.ProbeReason = "ok"
    seen: list[tuple[str, str, str]] = field(default_factory=list)

    async def __call__(self, login: str, password: str, folder: str) -> yadisk.ProbeResult:
        self.seen.append((login, password, folder))
        return yadisk.ProbeResult(self.reason, folder if self.reason == "ok" else None)


@dataclass
class Harness:
    client: TestClient
    storage: FakeStorage
    probe: FakeProbe
    yandex: FakeYandexProbe


@pytest.fixture
def harness(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[Harness]:
    settings = live_settings.model_copy(update={"secrets_key": SecretStr("k" * 64)})
    app = create_app(settings)
    with TestClient(app) as client:
        container = app.state.container
        storage, probe, yandex = FakeStorage(), FakeProbe(), FakeYandexProbe()
        container.offsite_connector = OffsiteConnectorService(
            container.session_factory,
            container.settings_service,
            container.secrets_store,
            storage,
            "offsite-config",
            probe,
            yandex,
            env="prod",
            lockout=LockoutPolicy(10, 15),
        )
        yield Harness(client, storage, probe, yandex)


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
    assert empty["provider"] == "yandex"  # ничего не настроено — по умолчанию Яндекс Диск
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
        "provider": "gdrive",
        "folder_id": FOLDER,
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


# --- Яндекс Диск (OPS-YADISK) ---------------------------------------------------------------------

LOGIN = "backup@example.org"
# Пароль приложения — фиктивный, из частей: 16 строчных латинских букв, как у Яндекса.
APP_PASSWORD = "fake" + "pass" + "word" + "test"


def ybody(**fields: object) -> dict[str, object]:
    out: dict[str, object] = {
        "provider": "yandex",
        "login": LOGIN,
        "folder_path": "",
        "app_password": APP_PASSWORD,
        "password": PASSWORD,
    }
    out.update(fields)
    return out


async def test_yandex_password_is_write_only_delivered_and_checked(
    sessions: async_sessionmaker[AsyncSession], harness: Harness
) -> None:
    client = harness.client
    auth = await headers(sessions, client, "admin")
    empty = client.get(URL, headers=auth).json()
    assert (empty["provider"], empty["default_folder_path"]) == ("yandex", "RailTech-backups/prod")
    assert empty["app_password_configured"] is False

    bad_login = client.put(URL, json=ybody(login="backup"), headers=auth)
    assert bad_login.json()["details"] == {"reason": "offsite_login_invalid", "field": "login"}
    bad_folder = client.put(URL, json=ybody(folder_path="../x"), headers=auth)
    assert bad_folder.json()["details"] == {
        "reason": "offsite_folder_invalid",
        "field": "folder_path",
    }
    no_password = client.put(URL, json=ybody(app_password=None), headers=auth)
    assert no_password.json()["details"] == {
        "reason": "offsite_app_password_invalid",
        "field": "app_password",
    }
    wrong = client.put(URL, json=ybody(password="nope"), headers=auth)
    assert wrong.json()["details"]["reason"] == "wrong_password"
    assert harness.storage.objects == {}

    spaced = " ".join(APP_PASSWORD[i : i + 4] for i in range(0, 16, 4))
    saved = client.put(
        URL, json=ybody(login=" Backup@Example.org ", app_password=spaced), headers=auth
    )
    assert saved.status_code == 200, saved.text
    status = saved.json()
    assert status["provider"] == "yandex"
    assert status["configured"] is True
    assert (status["login"], status["folder_path"]) == (LOGIN, "RailTech-backups/prod")
    assert status["app_password_configured"] is True
    assert status["last_check"]["reason"] == "ok"
    assert status["delivered_at"] is not None
    for text in (saved.text, client.get(URL, headers=auth).text):
        assert APP_PASSWORD not in text
        assert APP_PASSWORD[-4:] not in text
    assert harness.yandex.seen == [(LOGIN, APP_PASSWORD, "RailTech-backups/prod")]
    assert harness.storage.objects[("offsite-config", "yandex-password")] == APP_PASSWORD.encode()
    assert json.loads(harness.storage.objects[("offsite-config", "settings.json")]) == {
        "provider": "yandex",
        "login": LOGIN,
        "folder_path": "RailTech-backups/prod",
    }

    # Сменить только папку (кириллица): пароль прежний, доставляется снова.
    harness.yandex.reason = "no_space"
    moved = client.put(URL, json=ybody(app_password=None, folder_path="Бэкапы/прод"), headers=auth)
    assert moved.status_code == 200, moved.text
    assert (moved.json()["folder_path"], moved.json()["last_check"]["reason"]) == (
        "Бэкапы/прод",
        "no_space",
    )
    raw = harness.storage.objects[("offsite-config", "settings.json")]
    assert "Бэкапы/прод".encode() in raw  # без \\u-последовательностей: сервис читает строкой
    checked = client.post(f"{URL}/check", headers=auth)
    assert (checked.json()["ok"], checked.json()["reason"]) == (False, "no_space")
    assert harness.yandex.seen[-1] == (LOGIN, APP_PASSWORD, "Бэкапы/прод")

    async with sessions() as session:
        secret = await session.get(IntegrationSecret, "offsite_yandex_password")
        audits = (await session.execute(select(AuditLog))).scalars().all()
    assert secret is not None
    assert APP_PASSWORD.encode() not in secret.ciphertext
    assert secret.last4 == "****"  # последние символы пароля приложения не хранятся
    yandex = [a for a in audits if a.action == "integrations.offsite_yandex"]
    assert [(a.after or {})["password_changed"] for a in yandex] == [True, False]
    assert all(APP_PASSWORD not in repr((a.before, a.after)) for a in audits)


async def test_switching_providers_keeps_both_settings_and_checks_the_chosen_one(
    sessions: async_sessionmaker[AsyncSession], harness: Harness
) -> None:
    client = harness.client
    auth = await headers(sessions, client, "admin")
    assert client.put(URL, json=body(), headers=auth).status_code == 200
    assert client.get(URL, headers=auth).json()["provider"] == "gdrive"
    assert client.put(URL, json=ybody(), headers=auth).status_code == 200
    status = client.get(URL, headers=auth).json()
    assert (status["provider"], status["configured"], status["folder_id"]) == (
        "yandex",
        True,
        FOLDER,
    )
    harness.yandex.reason = "auth_failed"
    assert client.post(f"{URL}/check", headers=auth).json()["reason"] == "auth_failed"
    assert len(harness.probe.seen) == 1  # Google при выбранном Яндексе не проверяется

    # Обратно на Google Drive без нового ключа: ключ из хранилища доставляется снова.
    harness.storage.objects.clear()
    back = client.put(URL, json=body(key_json=None), headers=auth)
    assert back.status_code == 200, back.text
    assert back.json()["provider"] == "gdrive"
    assert harness.storage.objects[("offsite-config", "gdrive-sa.json")] == KEY.encode()

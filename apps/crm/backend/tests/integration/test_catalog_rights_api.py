"""Права прямого API CRM — только из каталога Платформы (D1-8, B-014) на настоящем Postgres.

Сотрудник с ролями Платформы получает права CRM из матриц своих ролей (`platform-rbac.yaml`):
базовая роль CRM (`viewer`/`manager`), которую система ему выводит, прав не даёт. Ожидания
строятся из самого `platform-rbac.yaml`, независимо от приложения: раздел и уровень роли → права
`ресурс:действие` (`backend.crm.read`, у `full` — ещё и `backend.crm.full`) → каждый ключевой
эндпоинт CRM требует своё право, и ответ ровно такой, какой даёт каталог: право есть — не отказ по
праву (чтения — 200), права нет — 403 «not allowed».

Переписка (B-D18-1): сообщения, вложения и заметки лида, ответ и заметка — `leads:<действие>` или
`chats:<действие>`; держатель только `chats:*` получает 404 — засеянный лид не его диалог (правило
участия и зоны — `test_chat_access_api.py`). Список диалогов `GET /chats` и имена `GET /team` —
`leads:read` или `chats:read`.

Случаи: шесть предустановок ролей (две системные и четыре шаблона), роль на каждый раздел с правами
CRM на каждом уровне (`crm.leads` full — менеджер по базовой роли, но без клиентов и сделок),
раздел без прав CRM, объединение двух ролей. Отдельно — `MessageOut` без `storage_key`.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.leads import Conversation
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services import message_log
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import PASSWORD, escalated_lead, login, make_user

pytestmark = pytest.mark.integration

CATALOG = yaml.safe_load(
    (
        Path(__file__).resolve().parents[5] / "packages" / "contracts" / "platform-rbac.yaml"
    ).read_text(encoding="utf-8")
)
RESOURCES: dict[str, dict[str, Any]] = {r["key"]: r for r in CATALOG["resources"]}
PRESETS: dict[str, dict[str, str]] = {
    **{code: role["access"] for code, role in CATALOG["system_roles"].items()},
    **{f"tpl:{code}": role["access"] for code, role in CATALOG["templates"].items()},
}

Right = tuple[str, str]


def crm_rights(access: dict[str, str]) -> set[Right]:
    """Права CRM по каталогу: раздел и уровень → `backend.crm.read` (+ `full` на уровне full)."""
    rights: set[Right] = set()
    for key, level in access.items():
        backend = ((RESOURCES[key].get("backend") or {}).get("crm")) or {}
        listed = list(backend.get("read", []))
        if level == "full":
            listed += list(backend.get("full", []))
        for perm in listed:
            resource, _, action = perm.partition(":")
            rights.add((resource, action))
    return rights


def levels_of(key: str) -> list[str]:
    return list(RESOURCES[key].get("levels") or ["read", "full"])


# Ключевые эндпоинты CRM и право, которое каждый требует (код приложения, не каталог).
# `{lead}` и `{message}` подставляются из засеянных данных.
Call = tuple[str, str, dict[str, Any] | None, Right]
READS: list[Call] = [
    ("GET", "/api/v1/inbox", None, ("leads", "read")),
    ("GET", "/api/v1/leads", None, ("leads", "read")),
    ("GET", "/api/v1/leads/{lead}", None, ("leads", "read")),
    ("GET", "/api/v1/team?section=eds.payments&level=full", None, ("users", "read")),
    ("GET", "/api/v1/clients", None, ("clients", "read")),
    ("GET", "/api/v1/deals", None, ("deals", "read")),
    ("GET", "/api/v1/documents", None, ("documents", "read")),
    ("GET", "/api/v1/dashboard", None, ("dashboard", "read")),
    ("GET", "/api/v1/users", None, ("users", "read")),
    ("GET", "/api/v1/platform-roles", None, ("users", "read")),
    ("GET", "/api/v1/settings", None, ("settings", "read")),
    ("GET", "/api/v1/reply-templates", None, ("reply_templates", "read")),
    ("GET", "/api/v1/spend", None, ("spend", "read")),
    ("GET", "/api/v1/audit", None, ("audit", "read")),
    ("GET", "/api/v1/integrations/erp", None, ("integrations", "read")),
]
# Изменения: право проверяется раньше объектных правил, поэтому «разрешено» = не отказ по праву
# (ответ может быть 403 по лиду, 404, 409 — это объектные правила, не каталог).
WRITES: list[Call] = [
    ("POST", "/api/v1/leads/{lead}/actions/take", None, ("leads", "take")),
    ("POST", "/api/v1/clients", {"name": "ООО Матрица"}, ("clients", "write")),
    ("POST", "/api/v1/deals", {"title": "Матрица прав"}, ("deals", "write")),
]


# Переписка лида (B-D18-1): `leads:<действие>` — любой диалог; только `chats:<действие>` — 404
# (засеянный лид не диалог сотрудника); ни того ни другого — 403 по праву.
DIALOG: list[tuple[str, str, dict[str, Any] | None, str]] = [
    ("GET", "/api/v1/leads/{lead}/messages", None, "read"),
    ("GET", "/api/v1/leads/{lead}/messages/{message}/attachments/0", None, "read"),
    ("GET", "/api/v1/leads/{lead}/notes", None, "read"),
    ("POST", "/api/v1/leads/{lead}/actions/note", {"text": "заметка"}, "note"),
    ("POST", "/api/v1/leads/{lead}/messages", {"text": "Здравствуйте"}, "reply"),
]
# Списки без объекта: достаточно реестра или переписки.
EITHER: list[str] = ["/api/v1/team", "/api/v1/chats"]


class StubStorage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    async def get(self, bucket: str, key: str) -> bytes:
        return self.files[key]


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        container = test_client.app.state.container  # type: ignore[attr-defined]
        storage = StubStorage()
        storage.files["tg/7101/1/Заявка.pdf"] = b"%PDF-1.4 demo"
        container.__dict__["storage"] = storage
        yield test_client


async def _seed(sessions: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    """Лид с сообщением и сохранённым вложением."""
    lead = await escalated_lead(sessions, tg_user_id=7101)
    async with sessions() as session, session.begin():
        conversation = (
            await session.scalars(select(Conversation).where(Conversation.lead_id == lead))
        ).one()
        message = await message_log.add(
            session,
            conversation,
            role="lead",
            text="Заявка во вложении",
            attachments=[
                {
                    "kind": "file",
                    "name": "Заявка.pdf",
                    "mime": "application/pdf",
                    "size": 13,
                    "storage_key": "tg/7101/1/Заявка.pdf",
                    "stored": True,
                }
            ],
        )
        return {"lead": lead, "message": message.id}


def _custom_role(
    admin: dict[str, str], client: TestClient, access: dict[str, str], name: str
) -> int:
    response = client.post(
        "/api/v1/platform-roles", json={"name": name, "access": access}, headers=admin
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


async def _staff_with(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    admin: dict[str, str],
    accesses: list[dict[str, str]],
    email: str,
) -> dict[str, str]:
    """Сотрудник с ролями по матрицам `accesses`; вход выполнен, пароль сменён."""
    account, _ = await make_user(sessions, email, ["viewer"])
    ids: list[int] = []
    async with sessions() as session:
        for number, access in enumerate(accesses):
            code = next((c for c, a in PRESETS.items() if a == access), None)
            if code is not None:
                (role,) = await prepo.by_codes(session, [code])
                ids.append(role.id)
            else:
                ids.append(_custom_role(admin, client, access, f"Матрица {email} {number}"))
    await UserService(sessions).update(Actor.system(), account.id, UserPatch(platform_role_ids=ids))
    return login(client, account.email, PASSWORD)


def _denied_by_right(response: Any) -> bool:
    if response.status_code != 403:
        return False
    body = response.json()
    return body.get("code") == "forbidden" and "is not allowed" in str(body.get("message"))


async def _check(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    accesses: list[dict[str, str]],
) -> None:
    ids = await _seed(sessions)
    boss_account, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    boss = login(client, boss_account.email, PASSWORD)
    headers = await _staff_with(client, sessions, boss, accesses, "matrix@railtech.uz")
    merged: dict[str, str] = {}
    for access in accesses:
        for key, level in access.items():
            if level == "full" or key not in merged:
                merged[key] = level
    rights = crm_rights(merged)

    for method, template, body, right in [*READS, *WRITES]:
        path = template.format(**ids)
        response = client.request(method, path, json=body, headers=headers)
        label = (method, path, right, sorted(merged.items()), response.status_code, response.text)
        if right in rights:
            assert not _denied_by_right(response), label
            if method == "GET":
                assert response.status_code == 200, label
        else:
            assert _denied_by_right(response), label

    for method, template, body, action in DIALOG:
        path = template.format(**ids)
        response = client.request(method, path, json=body, headers=headers)
        about = (method, path, action, sorted(merged.items()), response.status_code, response.text)
        if ("leads", action) in rights:
            assert not _denied_by_right(response), about
            if method == "GET":
                assert response.status_code == 200, about
        elif ("chats", action) in rights:
            assert response.status_code == 404, about
        else:
            assert _denied_by_right(response), about

    for path in EITHER:
        response = client.get(path, headers=headers)
        listed = (path, sorted(merged.items()), response.status_code, response.text)
        if {("leads", "read"), ("chats", "read")} & rights:
            assert response.status_code == 200, listed
        else:
            assert _denied_by_right(response), listed

    # Таблица прав самого API (`/me/permissions`) совпадает с каталогом.
    perms = client.get("/api/v1/me/permissions", headers=headers).json()["permissions"]
    given = {(res, act) for res, acts in perms.items() for act, ok in acts.items() if ok}
    assert given == rights


@pytest.mark.parametrize("code", list(PRESETS))
async def test_preset_role_gets_exactly_the_catalog_rights(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], code: str
) -> None:
    await _check(client, sessions, [PRESETS[code]])


def _crm_sections() -> list[tuple[str, str]]:
    return [
        (key, level)
        for key, res in RESOURCES.items()
        if (res.get("backend") or {}).get("crm")
        for level in levels_of(key)
    ]


@pytest.mark.parametrize(("section", "level"), _crm_sections())
async def test_single_section_role_gets_exactly_the_catalog_rights(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], section: str, level: str
) -> None:
    await _check(client, sessions, [{section: level}])


async def test_section_without_crm_rights_gives_no_crm_access(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Полный доступ к письмам EDS ничего не открывает в CRM, какова бы ни была базовая роль."""
    await _check(client, sessions, [{"eds.inbox": "full", "erp.calc": "full"}])


async def test_two_roles_are_united_by_maximum(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    await _check(client, sessions, [PRESETS["tpl:SUPPLY"], PRESETS["tpl:MANAGER"]])


async def test_supply_and_engineer_are_denied_the_lead_conversation(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Снабженец и инженер (нет ни `crm.leads`, ни `chats.external`): очередь, лиды, переписка и
    вложения сообщений — 403, как бы ни назвалась их базовая роль CRM."""
    ids = await _seed(sessions)
    boss_account, _ = await make_user(sessions, "boss@railtech.uz", ["admin"])
    boss = login(client, boss_account.email, PASSWORD)
    for number, code in enumerate(("tpl:SUPPLY", "tpl:ENGINEER")):
        headers = await _staff_with(
            client, sessions, boss, [PRESETS[code]], f"closed{number}@railtech.uz"
        )
        for path in (
            "/api/v1/inbox",
            "/api/v1/leads",
            "/api/v1/leads/{lead}",
            "/api/v1/leads/{lead}/messages",
            "/api/v1/leads/{lead}/messages/{message}/attachments/0",
        ):
            response = client.get(path.format(**ids), headers=headers)
            assert _denied_by_right(response), (code, path, response.status_code)


async def test_message_out_has_no_storage_key_and_the_file_comes_by_number(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """B-014: адрес в хранилище клиентам API не отдаётся; файл — потоком через маршрут вложения."""
    ids = await _seed(sessions)
    manager, password = await make_user(sessions, "manager@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)

    messages = client.get(f"/api/v1/leads/{ids['lead']}/messages", headers=headers).json()

    attached = [m for m in messages if m["attachments"]]
    assert len(attached) == 1
    (item,) = attached[0]["attachments"]
    assert "storage_key" not in item
    assert "tg/7101" not in str(messages)
    assert item == {
        "kind": "file",
        "name": "Заявка.pdf",
        "mime": "application/pdf",
        "size": 13,
        "stored": True,
    }
    file = client.get(
        f"/api/v1/leads/{ids['lead']}/messages/{attached[0]['id']}/attachments/0", headers=headers
    )
    assert (file.status_code, file.content) == (200, b"%PDF-1.4 demo")

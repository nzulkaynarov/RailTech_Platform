"""Системная роль «Администратор» в CRM (R3-D-2, решение архитектора 2026-10-23) на Postgres.

Права CRM сотрудника с ролями Платформы — только правила его ролей (`pr:<id>`). У системной
«Администратор» это раздел `admin` каталога (`platform-rbac.yaml`): сотрудники и роли, подключения,
модели ИИ, настройки, журнал — да; лиды, клиенты, сделки (чтение, действия, выгрузка) — нет. Базовая
роль CRM `admin` (`*:*`) ей прав не даёт. «Администратор» + «Директор» — права директора, но без
`leads:take/reply/...`.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import PASSWORD, escalated_lead, login, make_user

pytestmark = pytest.mark.integration

# Бизнес-данные CRM: системному администратору без второй роли — 403.
BUSINESS = [
    ("GET", "/api/v1/leads", None),
    ("GET", "/api/v1/leads/{lead}", None),
    ("GET", "/api/v1/leads/{lead}/messages", None),
    ("GET", "/api/v1/inbox", None),
    ("GET", "/api/v1/team", None),
    ("POST", "/api/v1/leads/{lead}/actions/take", None),
    ("POST", "/api/v1/leads/{lead}/actions/note", {"text": "x"}),
    ("POST", "/api/v1/leads/{lead}/messages", {"text": "Здравствуйте"}),
    ("GET", "/api/v1/stream", None),
    ("GET", "/api/v1/clients", None),
    ("POST", "/api/v1/clients", {"name": "ООО Демо"}),
    ("GET", "/api/v1/service-requests", None),
    ("GET", "/api/v1/documents", None),
    ("GET", "/api/v1/deals", None),
    ("POST", "/api/v1/deals", {"title": "Матрица прав"}),
    ("GET", "/api/v1/dashboard", None),
    ("GET", "/api/v1/export/leads.csv", None),
    ("GET", "/api/v1/export/clients.csv", None),
    ("GET", "/api/v1/export/deals.csv", None),
]
# Администрирование: 200.
ADMINISTRATION = [
    "/api/v1/users",
    "/api/v1/users/{employee}",
    "/api/v1/platform-roles",
    "/api/v1/setup/checklist",
    "/api/v1/settings",
    "/api/v1/integrations/telegram",
    "/api/v1/integrations/erp",
    "/api/v1/integrations/smtp",
    "/api/v1/admin/external-services",
    "/api/v1/models",
    "/api/v1/spend",
    "/api/v1/system/status",
    "/api/v1/system/backups",
    "/api/v1/audit",
    "/api/v1/reply-templates",
    "/api/v1/me",
    "/api/v1/me/permissions",
]


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def _staff(sessions: async_sessionmaker[AsyncSession], email: str, codes: list[str]) -> int:
    """Сотрудник с ролями Платформы по кодам (`ADMIN`, `DIRECTOR`), пароль уже сменён."""
    account, _ = await make_user(sessions, email, ["viewer"])
    async with sessions() as session:
        ids = [r.id for r in await prepo.by_codes(session, codes)]
    await UserService(sessions).update(Actor.system(), account.id, UserPatch(platform_role_ids=ids))
    return account.id


@pytest.fixture
async def ids(sessions: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    return {
        "lead": await escalated_lead(sessions),
        "employee": employee.id,
        "admin": await _staff(sessions, "admin@railtech.uz", ["ADMIN"]),
        "both": await _staff(sessions, "both@railtech.uz", ["ADMIN", "DIRECTOR"]),
    }


def _as(client: TestClient, email: str) -> dict[str, str]:
    return login(client, email, PASSWORD)


async def test_system_admin_has_no_business_data_in_crm(
    client: TestClient, ids: dict[str, int]
) -> None:
    headers = _as(client, "admin@railtech.uz")

    for method, template, body in BUSINESS:
        response = client.request(method, template.format(**ids), json=body, headers=headers)
        assert response.status_code == 403, (method, template, response.status_code)
        assert response.json()["code"] == "forbidden"


async def test_system_admin_administers_crm(client: TestClient, ids: dict[str, int]) -> None:
    headers = _as(client, "admin@railtech.uz")

    for template in ADMINISTRATION:
        response = client.get(template.format(**ids), headers=headers)
        assert response.status_code == 200, (template, response.status_code, response.text)
    changed = client.patch(
        f"/api/v1/users/{ids['employee']}", json={"position": "Менеджер"}, headers=headers
    )
    assert changed.status_code == 200, changed.text


async def test_system_admin_permissions_follow_the_catalog_admin_section(
    client: TestClient, ids: dict[str, int]
) -> None:
    body = client.get("/api/v1/me/permissions", headers=_as(client, "admin@railtech.uz")).json()
    perms = body["permissions"]

    for resource in ("leads", "stream", "clients", "deals", "documents", "dashboard"):
        assert not any(perms[resource].values()), (resource, perms[resource])
    for resource in ("users", "settings", "integrations", "models", "external_services"):
        assert all(perms[resource].values()), (resource, perms[resource])
    assert body["roles"] == [
        "admin"
    ]  # базовая роль CRM (старый фронт, «последний админ») — прежняя


async def test_admin_and_director_reads_like_a_director_but_does_not_work_the_leads(
    client: TestClient, ids: dict[str, int]
) -> None:
    headers = _as(client, "both@railtech.uz")

    for path in ("/api/v1/leads", "/api/v1/clients", "/api/v1/deals", "/api/v1/users"):
        assert client.get(path, headers=headers).status_code == 200, path
    for action in ("take", "note"):
        response = client.post(
            f"/api/v1/leads/{ids['lead']}/actions/{action}", json={"text": "x"}, headers=headers
        )
        assert response.status_code == 403, action
    reply = client.post(
        f"/api/v1/leads/{ids['lead']}/messages", json={"text": "Здравствуйте"}, headers=headers
    )
    assert reply.status_code == 403
    perms = client.get("/api/v1/me/permissions", headers=headers).json()["permissions"]
    assert perms["leads"] == {
        "read": True,
        "take": False,
        "work": False,
        "reply": False,
        "note": False,
        "assist": False,
        "create": False,
    }

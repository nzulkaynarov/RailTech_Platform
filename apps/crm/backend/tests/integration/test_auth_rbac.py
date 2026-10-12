"""Аутентификация и RBAC через REST на реальном Postgres (DoD Фазы 4: матрица роль × эндпоинт)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import AuditLog
from tests.integration.crm_helpers import PASSWORD, escalated_lead, login, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


@pytest.fixture
async def tokens(
    sessions: async_sessionmaker[AsyncSession], client: TestClient
) -> dict[str, dict[str, str]]:
    result = {}
    for role in ("admin", "manager", "viewer"):
        account, password = await make_user(sessions, f"{role}@railtech.uz", [role])
        result[role] = login(client, account.email, password)
    return result


# (метод, путь, тело) → роли, которым разрешено. «Разрешено» = не 401/403.
MATRIX = [
    ("GET", "/api/v1/leads", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/inbox", None, {"admin", "manager"}),  # SPEC §10.1: не наблюдателю
    ("GET", "/api/v1/team", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/leads/{lead}", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/leads/{lead}/messages", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/leads/{lead}/notes", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/leads/{lead}/decisions", None, {"admin", "manager", "viewer"}),
    ("POST", "/api/v1/leads/{lead}/actions/note", {"text": "x"}, {"admin", "manager"}),
    (
        "POST",
        "/api/v1/leads/{lead}/actions/snooze",
        {"until": "2000-01-01T00:00:00Z"},
        {"admin", "manager"},
    ),
    ("POST", "/api/v1/leads/{lead}/actions/unsnooze", None, {"admin", "manager"}),
    ("POST", "/api/v1/leads/{lead}/actions/close_won", {}, {"admin", "manager"}),
    ("POST", "/api/v1/leads/{lead}/actions/close_lost", {}, {"admin", "manager"}),
    ("POST", "/api/v1/leads/{lead}/actions/return_to_bot", {}, {"admin", "manager"}),
    ("POST", "/api/v1/leads/{lead}/messages", {"text": "Здравствуйте"}, {"admin", "manager"}),
    ("POST", "/api/v1/leads/{lead}/actions/take", None, {"admin", "manager"}),
    ("POST", "/api/v1/leads/{lead}/actions/new_deal", None, {"admin", "manager"}),
    ("POST", "/api/v1/leads/{lead}/actions/assign", {"user_id": 1}, {"admin", "manager"}),
    ("GET", "/api/v1/users", None, {"admin"}),
    ("GET", "/api/v1/users/{admin}", None, {"admin"}),
    (
        "POST",
        "/api/v1/users",
        {"email": "new@railtech.uz", "full_name": "N", "roles": ["viewer"]},
        {"admin"},
    ),
    ("PATCH", "/api/v1/users/{viewer}", {"full_name": "Viewer"}, {"admin"}),
    ("POST", "/api/v1/users/{viewer}/reset-password", None, {"admin"}),
    ("GET", "/api/v1/service-requests", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/service-requests?status=closed", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/me", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/me/permissions", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/setup/checklist", None, {"admin"}),
    ("GET", "/api/v1/system/backups", None, {"admin"}),
    # Волны F–G (аудит 2026-10-12): новые разделы. Платные (`/models/{a}/test`) и меняющие
    # систему вызовы (бэкап «сейчас», токен бота) здесь не дёргаются — у них свои тесты.
    ("GET", "/api/v1/system/status", None, {"admin"}),
    ("GET", "/api/v1/spend", None, {"admin"}),
    ("GET", "/api/v1/models", None, {"admin"}),
    ("GET", "/api/v1/integrations/telegram", None, {"admin"}),
    ("GET", "/api/v1/integrations/telegram/channels", None, {"admin"}),
    ("GET", "/api/v1/kb/products", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/deals", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/deals/summary", None, {"admin", "manager", "viewer"}),
    ("GET", "/api/v1/deals/options", None, {"admin", "manager", "viewer"}),
    ("POST", "/api/v1/deals", {"title": "Матрица прав"}, {"admin", "manager"}),
    # пустой текст → 422 до вызова модели; важно только «не 401/403»
    ("POST", "/api/v1/leads/{lead}/assist", {"mode": "improve", "text": ""}, {"admin", "manager"}),
    # Аудит админки §3 п. 1, §5: профиль бота, шаблоны ответов, экспорт CSV.
    ("GET", "/api/v1/integrations/telegram/profile", None, {"admin"}),
    ("PUT", "/api/v1/integrations/telegram/profile", {"name": {"ru": "x" * 65}}, {"admin"}),
    ("GET", "/api/v1/reply-templates", None, {"admin", "manager"}),
    (
        "POST",
        "/api/v1/reply-templates",
        {"title": "Матрица", "text": {"ru": "Здравствуйте, {name}!", "uz": "", "en": ""}},
        {"admin"},
    ),
    ("PUT", "/api/v1/reply-templates/999999", {"title": "x", "text": {}}, {"admin"}),
    ("DELETE", "/api/v1/reply-templates/999999", None, {"admin"}),
    ("GET", "/api/v1/export/leads.csv?stage=new", None, {"admin"}),
    ("GET", "/api/v1/export/clients.csv", None, {"admin"}),
    ("GET", "/api/v1/export/deals.csv?stage=won", None, {"admin"}),
]


@pytest.mark.parametrize("role", ["admin", "manager", "viewer"])
async def test_rbac_matrix(
    role: str,
    client: TestClient,
    tokens: dict[str, dict[str, str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    lead_id = await escalated_lead(sessions)
    ids = {"lead": lead_id, **{r: _user_id(client, tokens[r]) for r in tokens}}
    headers = tokens[role]
    for method, template, body, allowed in MATRIX:
        path = template.format(**ids)
        response = client.request(method, path, json=body, headers=headers)
        if role in allowed:
            assert response.status_code not in (401, 403), (role, method, path, response.text)
        else:
            assert response.status_code == 403, (role, method, path, response.status_code)


@pytest.mark.parametrize(("method", "template", "body", "_allowed"), MATRIX)
def test_anonymous_gets_401(
    method: str, template: str, body: object, _allowed: set[str], client: TestClient
) -> None:
    path = template.format(lead=1, admin=1, viewer=1)
    assert client.request(method, path, json=body).status_code == 401


def _user_id(client: TestClient, headers: dict[str, str]) -> int:
    return int(client.get("/api/v1/me", headers=headers).json()["id"])


async def test_lockout_after_ten_failures(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "lock@railtech.uz", ["manager"])
    codes = [
        client.post(
            "/api/v1/auth/login", json={"email": account.email, "password": "bad"}
        ).status_code
        for _ in range(10)
    ]
    assert codes == [401] * 9 + [423]
    good = client.post("/api/v1/auth/login", json={"email": account.email, "password": PASSWORD})
    assert good.status_code == 423
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@x.uz", "password": "x"})
    assert unknown.status_code == 401


async def test_refresh_rotation_and_reuse_detection(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "rot@railtech.uz", ["manager"])
    login(client, account.email, PASSWORD)
    first = client.cookies.get("rt_refresh") or ""
    assert first
    rotated = client.post("/api/v1/auth/refresh")
    assert rotated.status_code == 200
    second = client.cookies.get("rt_refresh") or ""
    assert second != first
    client.cookies.set("rt_refresh", first, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401
    client.cookies.set("rt_refresh", second, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401  # семейство отозвано


async def test_logout_revokes_refresh(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, _ = await make_user(sessions, "out@railtech.uz", ["viewer"])
    login(client, account.email, PASSWORD)
    token = client.cookies.get("rt_refresh") or ""
    assert client.post("/api/v1/auth/logout").status_code == 204
    client.cookies.set("rt_refresh", token, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


async def test_temporary_password_forces_change(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    account, temporary = await make_user(sessions, "temp@railtech.uz", ["manager"], ready=False)
    headers = login(client, account.email, temporary)
    blocked = client.get("/api/v1/leads", headers=headers)
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "password_change_required"
    perms = client.get("/api/v1/me/permissions", headers=headers).json()["permissions"]
    assert not perms["leads"]["read"]
    weak = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": temporary, "new_password": "short"},
        headers=headers,
    )
    assert weak.status_code == 422
    assert weak.json()["details"] == {"reason": "weak_password", "field": "new_password"}
    wrong = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "not-the-password-1", "new_password": PASSWORD},
        headers=headers,
    )
    assert wrong.status_code == 422
    assert wrong.json()["details"] == {"reason": "wrong_password", "field": "current_password"}
    changed = client.post(
        "/api/v1/auth/change-password",
        json={"current_password": temporary, "new_password": PASSWORD},
        headers=headers,
    )
    assert changed.status_code == 204
    assert client.get("/api/v1/leads", headers=headers).status_code == 200


async def test_last_admin_is_protected(
    client: TestClient, tokens: dict[str, dict[str, str]]
) -> None:
    admin_id = _user_id(client, tokens["admin"])
    demote = client.patch(
        f"/api/v1/users/{admin_id}", json={"roles": ["manager"]}, headers=tokens["admin"]
    )
    assert demote.status_code == 409
    assert demote.json()["code"] == "last_admin"
    deactivate = client.patch(
        f"/api/v1/users/{admin_id}", json={"is_active": False}, headers=tokens["admin"]
    )
    assert deactivate.status_code == 409
    second = client.post(
        "/api/v1/users",
        json={"email": "admin2@railtech.uz", "full_name": "Admin 2", "roles": ["admin"]},
        headers=tokens["admin"],
    )
    assert second.status_code == 201
    assert second.json()["temporary_password"]
    duplicate = client.post(
        "/api/v1/users",
        json={"email": "admin2@railtech.uz", "full_name": "Admin 2", "roles": ["admin"]},
        headers=tokens["admin"],
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["details"] == {"reason": "email_taken", "field": "email"}
    assert (
        client.patch(
            f"/api/v1/users/{admin_id}",
            json={"roles": ["manager", "viewer"]},
            headers=tokens["admin"],
        ).status_code
        == 200
    )


async def test_deactivated_user_loses_access_immediately(
    client: TestClient, tokens: dict[str, dict[str, str]]
) -> None:
    viewer_id = _user_id(client, tokens["viewer"])
    client.patch(f"/api/v1/users/{viewer_id}", json={"is_active": False}, headers=tokens["admin"])
    assert client.get("/api/v1/leads", headers=tokens["viewer"]).status_code == 401


async def test_mutations_are_audited(
    client: TestClient,
    tokens: dict[str, dict[str, str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    client.post(
        "/api/v1/users",
        json={"email": "aud@railtech.uz", "full_name": "A", "roles": ["viewer"]},
        headers=tokens["admin"],
    )
    async with sessions() as session:
        actions = set((await session.scalars(select(AuditLog.action))).all())
        logins = await session.scalar(
            select(func.count()).select_from(AuditLog).where(AuditLog.action == "auth.login")
        )
    assert {"user.create", "auth.login"} <= actions
    assert logins == 3


async def test_templates_crud_and_csv_export_are_audited(
    client: TestClient,
    tokens: dict[str, dict[str, str]],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    admin = tokens["admin"]
    body = {"title": "КП", "text": {"ru": "Пришлю КП, {name}", "uz": "", "en": ""}}
    created = client.post("/api/v1/reply-templates", json=body, headers=admin)
    assert created.status_code == 201
    template_id = created.json()["id"]
    body["title"] = "КП сегодня"
    assert client.put(f"/api/v1/reply-templates/{template_id}", json=body, headers=admin).is_success
    listed = client.get("/api/v1/reply-templates", headers=tokens["manager"]).json()
    assert [t["title"] for t in listed] == ["КП сегодня"]
    assert client.delete(f"/api/v1/reply-templates/{template_id}", headers=admin).is_success

    await escalated_lead(sessions)
    csv = client.get("/api/v1/export/leads.csv", headers=admin)
    assert csv.status_code == 200
    assert csv.headers["content-type"].startswith("text/csv")
    text = csv.content.decode("utf-8")
    assert text.startswith("\ufeffID;Имя;Язык;Стадия")
    assert len(text.strip().splitlines()) >= 2
    async with sessions() as session:
        actions = set((await session.scalars(select(AuditLog.action))).all())
    assert {
        "reply_template.create",
        "reply_template.update",
        "reply_template.delete",
        "export.leads",
    } <= actions

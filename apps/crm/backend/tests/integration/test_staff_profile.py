"""Профиль сотрудника на реальной БД (W15-H6): поля, фото, права «только свой профиль»."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.errors import ValidationFailedError
from app.main import create_app
from app.models.auth import AuditLog, User
from app.security.audit import Actor
from app.services.staff_profile import StaffProfileService
from app.services.users import UserService
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> None:
        self.objects[(bucket, key)] = data

    async def get(self, bucket: str, key: str) -> bytes:
        return self.objects[(bucket, key)]

    async def delete(self, bucket: str, key: str) -> None:
        self.objects.pop((bucket, key), None)


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


def service(
    sessions: async_sessionmaker[AsyncSession],
) -> tuple[StaffProfileService, MemoryStorage]:
    storage = MemoryStorage()
    return StaffProfileService(
        sessions, UserService(sessions), storage, "client-documents"
    ), storage


async def test_employee_edits_own_profile_fields(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    me = client.get("/api/v1/me", headers=headers).json()
    assert (me["phone"], me["timezone"], me["email_signature"]) == (None, "Asia/Tashkent", None)
    assert me["avatar_version"] is None
    assert me["deputy_user_id"] is None

    response = client.patch(
        "/api/v1/me",
        headers=headers,
        json={
            "full_name": "Дильшод Т.",
            "phone": "+998 90 123-45-67",
            "timezone": "Asia/Samarkand",
            "email_signature": "С уважением,\nДильшод",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == "Дильшод Т."
    assert body["phone"] == "+998901234567"
    assert body["timezone"] == "Asia/Samarkand"
    assert body["email_signature"] == "С уважением,\nДильшод"

    # Пустая строка очищает телефон и подпись.
    cleared = client.patch(
        "/api/v1/me", headers=headers, json={"phone": "", "email_signature": " "}
    ).json()
    assert cleared["phone"] is None
    assert cleared["email_signature"] is None

    async with sessions() as session:
        entries = list(
            await session.scalars(select(AuditLog).where(AuditLog.action == "user.profile_update"))
        )
    assert entries
    assert "Дильшод" not in str([(e.before, e.after) for e in entries])  # подпись в журнал не пишем


@pytest.mark.parametrize(
    ("payload", "field", "reason"),
    [
        ({"phone": "abc"}, "phone", "phone_invalid"),
        ({"timezone": "Mars/Base"}, "timezone", "timezone_unknown"),
        ({"email_signature": "a\u0000b"}, "email_signature", "signature_invalid"),
    ],
)
async def test_invalid_values_are_422_with_field_and_reason(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    payload: dict[str, Any],
    field: str,
    reason: str,
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    response = client.patch(
        "/api/v1/me", headers=login(client, manager.email, password), json=payload
    )
    assert response.status_code == 422
    assert response.json()["details"]["field"] == field
    assert response.json()["details"]["reason"] == reason


async def test_only_own_profile_and_position_is_read_only(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    other, _ = await make_user(sessions, "other@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)

    # Должность, роли и чужой id в профиль не принимаются: 422, ничего не меняется.
    for forbidden in ({"position": "Директор"}, {"user_id": other.id, "phone": "+998901234567"}):
        assert client.patch("/api/v1/me", headers=headers, json=forbidden).status_code == 422
    # Чужой профиль админским путём менеджеру недоступен.
    assert (
        client.patch(
            f"/api/v1/users/{other.id}", headers=headers, json={"full_name": "Взлом"}
        ).status_code
        == 403
    )
    async with sessions() as session:
        stored = await session.get(User, other.id)
    assert stored is not None
    assert stored.phone is None
    assert stored.full_name != "Взлом"
    assert stored.position is None


async def test_avatar_roundtrip_replace_and_remove(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, storage = service(sessions)
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    actor = Actor(employee.id)

    view = await svc.set_avatar(actor, employee.id, PNG, "image/png")
    assert view.avatar_version is not None
    first = await svc.read_avatar(employee.id)
    assert first is not None
    assert first.content_type == "image/png"
    assert first.data == PNG
    assert len(storage.objects) == 1
    ((bucket, key),) = storage.objects
    assert bucket == "client-documents"
    assert key.startswith(f"staff-avatars/{employee.id}/")

    await svc.set_avatar(actor, employee.id, JPEG, "image/jpeg")
    assert len(storage.objects) == 1  # прежний файл удалён, а не накоплен
    second = await svc.read_avatar(employee.id)
    assert second is not None
    assert second.content_type == "image/jpeg"

    view = await svc.remove_avatar(actor, employee.id)
    assert view.avatar_version is None
    assert not storage.objects
    assert await svc.read_avatar(employee.id) is None


@pytest.mark.parametrize(
    ("data", "claimed", "reason"),
    [
        (b"<svg onload=alert(1)>", "image/svg+xml", "avatar_unsupported_type"),
        (b"", "image/png", "avatar_empty"),
        (PNG, "image/jpeg", "avatar_type_mismatch"),
        (PNG + b"0" * (1024 * 1024), "image/png", "avatar_too_large"),
    ],
)
async def test_bad_avatar_is_rejected_and_nothing_is_stored(
    sessions: async_sessionmaker[AsyncSession], data: bytes, claimed: str, reason: str
) -> None:
    svc, storage = service(sessions)
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    with pytest.raises(ValidationFailedError) as caught:
        await svc.set_avatar(Actor(employee.id), employee.id, data, claimed)
    assert caught.value.details["reason"] == reason
    assert not storage.objects
    assert await svc.read_avatar(employee.id) is None


async def test_deactivated_employee_avatar_is_hidden(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    svc, _ = service(sessions)
    employee, _ = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    await svc.set_avatar(Actor(employee.id), employee.id, PNG, "image/png")
    async with sessions() as session, session.begin():
        user = await session.get(User, employee.id)
        assert user is not None
        user.is_active = False
    assert await svc.read_avatar(employee.id) is None


async def test_avatar_api_guards(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    assert client.get(f"/api/v1/staff/{manager.id}/avatar").status_code == 401
    assert client.get(f"/api/v1/staff/{manager.id}/avatar", headers=headers).status_code == 404
    svg = {"avatar": ("a.svg", b"<svg onload=alert(1)>", "image/svg+xml")}
    response = client.put("/api/v1/me/avatar", headers=headers, files=svg)
    assert response.status_code == 422
    assert response.json()["details"]["reason"] == "avatar_unsupported_type"


async def test_avatar_body_is_cut_off_at_the_limit(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Тело больше 1 МБ + запас не дочитывается: 413 до разбора формы и до S3."""
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    huge = {"avatar": ("a.png", PNG + b"\x00" * (1024 * 1024 + 70_000), "image/png")}
    response = client.put("/api/v1/me/avatar", headers=headers, files=huge)
    assert response.status_code == 413
    assert response.json()["code"] == "payload_too_large"
    assert response.json()["details"]["reason"] == "avatar_too_large"

    # Без Content-Length (chunked) предел действует так же: тело читается потоком.
    def chunks() -> Iterator[bytes]:
        boundary_open = b'--xyz\r\nContent-Disposition: form-data; name="avatar"; filename="a"\r\n'
        yield boundary_open + b"Content-Type: image/png\r\n\r\n"
        for _ in range(40):
            yield b"\x00" * 65_536
        yield b"\r\n--xyz--\r\n"

    streamed = client.put(
        "/api/v1/me/avatar",
        headers={**headers, "Content-Type": "multipart/form-data; boundary=xyz"},
        content=chunks(),
    )
    assert streamed.status_code == 413


async def test_avatar_without_the_field_or_not_multipart_is_422(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    other = client.put(
        "/api/v1/me/avatar", headers=headers, files={"file": ("a.png", PNG, "image/png")}
    )
    assert other.status_code == 422
    assert other.json()["details"]["reason"] == "avatar_empty"
    plain = client.put(
        "/api/v1/me/avatar", headers={**headers, "Content-Type": "image/png"}, content=PNG
    )
    assert plain.status_code == 422
    assert plain.json()["details"]["reason"] == "avatar_unsupported_type"


async def test_patch_me_is_atomic_and_rejects_a_blank_name(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Одна ошибка в теле — ничего не сохранено (язык и подписки тоже)."""
    manager, password = await make_user(sessions, "dilshod@railtech.uz", ["manager"])
    headers = login(client, manager.email, password)
    for body, field in (
        ({"language": "uz", "notify_leads": False, "phone": "abc"}, "phone"),
        ({"language": "uz", "full_name": "   "}, "full_name"),
        ({"language": "uz", "ui_mode": "admin"}, "ui_mode"),
    ):
        response = client.patch("/api/v1/me", headers=headers, json=body)
        assert response.status_code == 422, body
        assert response.json()["details"]["field"] == field
    me = client.get("/api/v1/me", headers=headers).json()
    assert me["language"] == "ru"
    assert me["notify_leads"] is True
    assert me["full_name"] == "dilshod"


async def test_patch_me_waits_for_the_temporary_password_to_be_changed(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    employee, temporary = await make_user(sessions, "new@railtech.uz", ["manager"], ready=False)
    headers = login(client, employee.email, temporary)
    response = client.patch("/api/v1/me", headers=headers, json={"language": "uz"})
    assert response.status_code == 403

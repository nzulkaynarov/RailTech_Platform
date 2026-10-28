"""«Что нового» Платформы: отметки сотрудника в CRM на реальной БД (W-REL)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from tests.integration.crm_helpers import login, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def test_api_whats_new_marks_only_grow_and_belong_to_me(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> None:
    user, password = await make_user(sessions, "reader@railtech.uz", ["manager"])
    other, other_password = await make_user(sessions, "other@railtech.uz", ["manager"])
    headers = login(client, user.email, password)

    # Ничего не видел: обе отметки пустые.
    me = client.get("/api/v1/me", headers=headers).json()
    assert me["whats_new_shown"] is None
    assert me["whats_new_read"] is None

    # Закрыл окно «Платформа обновлена», раздел не открывал: отметка «Новое» у «?» остаётся.
    shown = client.patch("/api/v1/me", headers=headers, json={"whats_new_shown": "2026-10-28"})
    assert shown.status_code == 200, shown.text
    assert shown.json()["whats_new_shown"] == "2026-10-28"
    assert shown.json()["whats_new_read"] is None

    # Более ранняя запись отметку не откатывает.
    back = client.patch("/api/v1/me", headers=headers, json={"whats_new_shown": "2026-10-01"})
    assert back.json()["whats_new_shown"] == "2026-10-28"

    # Открыл «Что нового» новой записи — и окно о ней больше не нужно.
    read = client.patch("/api/v1/me", headers=headers, json={"whats_new_read": "2026-11-02"})
    assert read.json()["whats_new_read"] == "2026-11-02"
    assert read.json()["whats_new_shown"] == "2026-11-02"

    # Формат — дата записи; другое — 422, ничего не сохранено.
    bad = client.patch("/api/v1/me", headers=headers, json={"whats_new_read": "v2"})
    assert bad.status_code == 422

    # Отметки — свои: у другого сотрудника пусто.
    other_headers = login(client, other.email, other_password)
    assert client.get("/api/v1/me", headers=other_headers).json()["whats_new_read"] is None

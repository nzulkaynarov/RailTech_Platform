"""«Журнал интеграций» шины CRM (`/api/v1/bus/*`, W13-A2) на Postgres: сводка, доставки и DLQ,
inbox с ошибками, повторы (идемпотентно, с записью в журнал аудита) и права.

Права — раздел `admin` каталога Платформы: «Администратор» (`admin: full`) читает и повторяет;
«Директор» (`admin: read`) только читает; роль без раздела — 403. Тел событий в ответах нет.
"""

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import PASSWORD, login, make_user
from tests.integration.roles_helpers import audit_rows

pytestmark = pytest.mark.integration

EVENT = uuid.UUID("0b9c3c1e-7d0a-4f55-9a43-6a2f4f1d2a01")
FAILED = uuid.UUID("5d7e1f0a-2b3c-4d5e-8f90-a1b2c3d4e5f6")
CLIENT_UPDATED = "uz.railtech.crm.client.updated.v1"
RETRY_DEAD = "/api/v1/bus/deliveries/retry-dead"
ERP = {"subscriber": "erp"}


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def _staff(sessions: async_sessionmaker[AsyncSession], email: str, codes: list[str]) -> int:
    account, _ = await make_user(sessions, email, ["viewer"])
    async with sessions() as session:
        ids = [r.id for r in await prepo.by_codes(session, codes)]
    await UserService(sessions).update(Actor.system(), account.id, UserPatch(platform_role_ids=ids))
    return account.id


@pytest.fixture
async def staff(sessions: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    return {
        "admin": await _staff(sessions, "admin@railtech.uz", ["ADMIN"]),
        "director": await _staff(sessions, "director@railtech.uz", ["DIRECTOR"]),
        "manager": await _staff(sessions, "manager@railtech.uz", ["tpl:MANAGER"]),
    }


@pytest.fixture
async def journal(sessions: async_sessionmaker[AsyncSession], staff: dict[str, int]) -> None:
    """Событие CRM, доставка которого в ERP ушла в DLQ (404), и входящее событие ERP с упавшей
    обработкой."""
    async with sessions() as session, session.begin():
        for table in ("rt_bus_outbox", "rt_bus_delivery", "rt_bus_inbox"):
            await session.execute(text(f"DELETE FROM {table}"))  # noqa: S608 — имена таблиц шины
        await session.execute(
            text(
                "INSERT INTO rt_bus_outbox (id, type, source, subject, correlation_id, envelope,"
                " created_at, dispatched_at) VALUES (:id, :type, 'rt://crm', 'client/7',"
                " 'req-journal-1', CAST(:envelope AS jsonb), now(), now())"
            ),
            {"id": EVENT, "type": CLIENT_UPDATED, "envelope": '{"data": {"name": "ООО Демо"}}'},
        )
        await session.execute(
            text(
                "INSERT INTO rt_bus_delivery (event_id, event_type, subscriber, status, attempts,"
                " created_at, updated_at, last_status_code, last_error) VALUES (:id, :type, 'erp',"
                " 'dead', 1, now(), now(), 404, 'HTTP 404: not found')"
            ),
            {"id": EVENT, "type": CLIENT_UPDATED},
        )
        await session.execute(
            text(
                "INSERT INTO rt_bus_inbox (event_id, type, source, publisher, subject,"
                " correlation_id, envelope, status, attempts, error, received_at, updated_at)"
                " VALUES (:id,"
                " 'uz.railtech.erp.deal.won.v1', 'rt://erp', 'erp', 'ЗВ-2026-104', 'req-journal-2',"
                " CAST('{}' AS jsonb), 'failed', 4, 'ValueError: deal is not known', now(), now())"
            ),
            {"id": FAILED},
        )


def _as(client: TestClient, who: str) -> dict[str, str]:
    return login(client, f"{who}@railtech.uz", PASSWORD)


async def test_admin_sees_overview_dlq_and_failed_inbox_without_event_bodies(
    client: TestClient, journal: None
) -> None:
    headers = _as(client, "admin")
    overview = client.get("/api/v1/bus/overview", headers=headers)
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert (body["service"], body["dlq_size"], body["inbox_failed"]) == ("crm", 1, 1)
    subs = {s["name"]: s for s in body["subscribers"]}
    # CRM доставляет свои события (crm, identity) ERP, EDS и BFF; себе — нет
    assert set(subs) == {"eds", "erp", "platform-bff"}
    erp = subs["erp"]
    assert (erp["dead"], erp["configured"], erp["paused_until"]) == (1, True, None)

    dead = client.get("/api/v1/bus/deliveries", params={"status": "dead"}, headers=headers)
    assert dead.status_code == 200, dead.text
    [row] = dead.json()["items"]
    assert dead.json()["has_more"] is False
    assert (row["event_id"], row["subscriber"], row["last_status_code"]) == (str(EVENT), "erp", 404)
    assert (row["subject"], row["correlation_id"]) == ("client/7", "req-journal-1")
    assert "envelope" not in row
    assert "data" not in row
    assert "ООО Демо" not in dead.text  # тело события не уходит в журнал

    filtered = client.get(
        "/api/v1/bus/deliveries", params={"type": "lead.", "subscriber": "erp"}, headers=headers
    )
    assert filtered.json() == {"items": [], "has_more": False}

    inbox = client.get("/api/v1/bus/inbox", params={"errors": "true"}, headers=headers)
    assert inbox.status_code == 200, inbox.text
    [entry] = inbox.json()["items"]
    assert (entry["event_id"], entry["status"]) == (str(FAILED), "failed")
    assert entry["publisher"] == "erp"
    assert entry["error"] == "ValueError: deal is not known"


async def test_retries_are_idempotent_and_audited(
    client: TestClient,
    journal: None,
    staff: dict[str, int],
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    headers = _as(client, "admin")
    dead = client.get("/api/v1/bus/deliveries", params={"status": "dead"}, headers=headers)
    delivery_id = dead.json()["items"][0]["id"]

    assert client.post(RETRY_DEAD, json=ERP, headers=headers).json() == {"retried": 1}
    assert client.post(RETRY_DEAD, json=ERP, headers=headers).json() == {"retried": 0}
    # ожидающую доставку «Повторить» отправляет сейчас (попытки с нуля): повтор безопасен
    again = client.post(f"/api/v1/bus/deliveries/{delivery_id}/retry", headers=headers)
    assert again.json() == {"retried": 1}
    assert client.post("/api/v1/bus/deliveries/999999/retry", headers=headers).json() == {
        "retried": 0
    }
    pending = client.get("/api/v1/bus/deliveries", params={"status": "pending"}, headers=headers)
    assert [(d["id"], d["attempts"]) for d in pending.json()["items"]] == [(delivery_id, 0)]

    assert client.post(f"/api/v1/bus/inbox/{FAILED}/retry", headers=headers).json() == {
        "retried": 1
    }
    assert client.post(f"/api/v1/bus/inbox/{FAILED}/retry", headers=headers).json() == {
        "retried": 0
    }

    dead_rows = await audit_rows(sessions, "bus.dead_retried")
    assert [(r.actor_user_id, r.entity_id, r.after) for r in dead_rows] == [
        (staff["admin"], "erp", {"retried": 1}),
        (staff["admin"], "erp", {"retried": 0}),
    ]
    assert len(await audit_rows(sessions, "bus.delivery_retried")) == 2
    inbox_rows = await audit_rows(sessions, "bus.inbox_retried")
    assert [r.entity_id for r in inbox_rows] == [str(FAILED), str(FAILED)]


async def test_director_reads_only_and_role_without_admin_gets_403(
    client: TestClient, journal: None
) -> None:
    director = _as(client, "director")
    assert client.get("/api/v1/bus/overview", headers=director).status_code == 200
    assert client.get("/api/v1/bus/deliveries", headers=director).status_code == 200
    for path in (
        "/api/v1/bus/deliveries/1/retry",
        RETRY_DEAD,
        f"/api/v1/bus/inbox/{FAILED}/retry",
    ):
        response = client.post(path, json=ERP, headers=director)
        assert response.status_code == 403, (path, response.status_code)

    manager = _as(client, "manager")
    for path in ("/api/v1/bus/overview", "/api/v1/bus/deliveries", "/api/v1/bus/inbox"):
        response = client.get(path, headers=manager)
        assert response.status_code == 403, (path, response.status_code)
        assert response.json()["code"] == "forbidden"
    assert client.get("/api/v1/bus/overview").status_code == 401


async def test_filters_are_validated(client: TestClient, journal: None) -> None:
    headers = _as(client, "admin")
    for params in ({"status": "lost"}, {"limit": 500}, {"subscriber": "ERP!"}, {"before_id": 0}):
        response = client.get("/api/v1/bus/deliveries", params=params, headers=headers)
        assert response.status_code == 422, (params, response.status_code)
    bad_inbox = client.get("/api/v1/bus/inbox", params={"status": "dead"}, headers=headers)
    assert bad_inbox.status_code == 422
    page = client.get("/api/v1/bus/deliveries", params={"limit": 1}, headers=headers).json()
    assert (len(page["items"]), page["has_more"]) == (1, False)

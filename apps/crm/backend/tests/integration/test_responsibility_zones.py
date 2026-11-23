"""Реестр зон ответственности (ЕВ-З): девять зон без людей, права, проблемы по фактам, журнал."""

from collections.abc import Iterator
from datetime import date, timedelta

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.domain.platform_roles_generated import RESOURCE_KEYS
from app.main import create_app
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import login, make_user
from tests.integration.roles_helpers import audit_rows

pytestmark = pytest.mark.integration
ZONES = "/api/v1/responsibility-zones"
BEFORE = "4d6593eef5f9"
NINE = {
    "finance",
    "legal",
    "sales",
    "first_contact",
    "records",
    "supply",
    "projects",
    "people",
    "it_settings",
}
NEW_ZONE = {
    "code": "quality",
    "name": {"ru": "Качество", "uz": "Sifat", "en": "Quality"},
    "description": {"ru": "Рекламации", "uz": "", "en": "Complaints"},
    "sections": ["crm.clients", "erp.stock"],
}


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def _staff(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    email: str,
    codes: list[str],
) -> tuple[int, dict[str, str]]:
    account, password = await make_user(sessions, email, ["viewer"])
    async with sessions() as session:
        ids = [r.id for r in await prepo.by_codes(session, codes)]
    await UserService(sessions).update(Actor.system(), account.id, UserPatch(platform_role_ids=ids))
    return account.id, login(client, account.email, password)


@pytest.fixture
async def staff(
    client: TestClient, sessions: async_sessionmaker[AsyncSession]
) -> dict[str, tuple[int, dict[str, str]]]:
    return {
        "admin": await _staff(client, sessions, "admin@railtech.uz", ["ADMIN"]),
        "director": await _staff(client, sessions, "director@railtech.uz", ["DIRECTOR"]),
        "manager": await _staff(client, sessions, "manager@railtech.uz", ["tpl:MANAGER"]),
    }


def _create(client: TestClient, headers: dict[str, str], **over: object) -> dict[str, object]:
    response = client.post(ZONES, json={**NEW_ZONE, **over}, headers=headers)
    assert response.status_code == 201, response.text
    created: dict[str, object] = response.json()
    return created


def _codes(zone: dict[str, object]) -> list[str]:
    problems = zone["problems"]
    assert isinstance(problems, list)
    return [p["code"] for p in problems]


# --- миграция и зерно ---------------------------------------------------------------------------


def test_seed_has_nine_zones_without_people_and_the_migration_is_reversible(
    alembic_config: Config, live_settings: Settings
) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, BEFORE)
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        assert conn.execute("SELECT to_regclass('responsibility_zones')").fetchone() == (None,)
    command.upgrade(alembic_config, "head")
    with psycopg.connect(live_settings.libpq_dsn) as conn:
        rows = conn.execute(
            "SELECT code, sections, responsible_user_id, deputy_user_id, curator_user_id, "
            "name_uz, description_uz, name_en, description_ru FROM responsibility_zones"
        ).fetchall()
    assert {r[0] for r in rows} == NINE
    for code, sections, *people_and_texts in rows:
        assert people_and_texts[:3] == [None, None, None], code
        assert sections, code
        assert set(sections) <= set(RESOURCE_KEYS), code
        assert all(people_and_texts[3:]), code
        uz = f"{people_and_texts[3]} {people_and_texts[4]}".lower()
        # Узбекский — новый алфавит: ö ğ ş ç вместо oʻ gʻ sh ch.
        for old in ("sh", "ch", "o‘", "g‘", "oʻ", "gʻ", "'"):
            assert old not in uz, (code, old)


# --- права -------------------------------------------------------------------------------------


async def test_permission_matrix_admin_director_manager(
    client: TestClient, staff: dict[str, tuple[int, dict[str, str]]]
) -> None:
    admin, director, manager = (staff[k][1] for k in ("admin", "director", "manager"))
    zone = _create(client, admin)
    zid = zone["id"]
    assert client.get(ZONES, headers=admin).status_code == 200
    assert client.get(ZONES, headers=director).status_code == 200
    assert client.get(ZONES, headers=manager).status_code == 403
    # Завести и выключить — только администратор.
    assert (
        client.post(ZONES, json={**NEW_ZONE, "code": "other"}, headers=director).status_code == 403
    )
    assert client.post(f"{ZONES}/{zid}/deactivate", headers=director).status_code == 403
    assert client.post(f"{ZONES}/{zid}/deactivate", headers=manager).status_code == 403
    # Назначить людей — администратор и директор.
    body = {"responsible_user_id": staff["director"][0]}
    assert client.patch(f"{ZONES}/{zid}", json=body, headers=manager).status_code == 403
    assert client.patch(f"{ZONES}/{zid}", json=body, headers=director).status_code == 200
    assert client.patch(f"{ZONES}/{zid}", json=body, headers=admin).status_code == 200
    assert client.post(f"{ZONES}/{zid}/deactivate", headers=admin).status_code == 200


async def test_reader_without_company_settings_cannot_assign_people(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    staff: dict[str, tuple[int, dict[str, str]]],
) -> None:
    """Роль только с чтением сотрудников видит реестр, но назначать людей не может."""
    admin = staff["admin"][1]
    zid = _create(client, admin)["id"]
    role = client.post(
        "/api/v1/platform-roles",
        json={"name": "Читатель", "access": {"admin": "read"}},
        headers=admin,
    ).json()
    account, password = await make_user(sessions, "reader@railtech.uz", ["viewer"])
    patched = client.patch(
        f"/api/v1/users/{account.id}", json={"platform_role_ids": [role["id"]]}, headers=admin
    )
    assert patched.status_code == 200, patched.text
    reader = login(client, account.email, password)
    assert client.get(ZONES, headers=reader).status_code == 200
    body = {"responsible_user_id": staff["director"][0]}
    assert client.patch(f"{ZONES}/{zid}", json=body, headers=reader).status_code == 403


# --- создание и проверки -----------------------------------------------------------------------


async def test_create_validates_sections_code_and_names(
    client: TestClient, staff: dict[str, tuple[int, dict[str, str]]]
) -> None:
    admin = staff["admin"][1]
    unknown = client.post(ZONES, json={**NEW_ZONE, "sections": ["no.such"]}, headers=admin)
    assert unknown.status_code == 422
    assert unknown.json()["details"]["field"] == "sections"
    assert client.post(ZONES, json={**NEW_ZONE, "sections": []}, headers=admin).status_code == 422
    assert (
        client.post(ZONES, json={**NEW_ZONE, "code": "Bad Code"}, headers=admin).status_code == 422
    )
    _create(client, admin)
    assert client.post(ZONES, json=NEW_ZONE, headers=admin).status_code == 409


async def test_assign_rejects_unknown_inactive_same_person_and_reversed_term(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    staff: dict[str, tuple[int, dict[str, str]]],
) -> None:
    admin = staff["admin"][1]
    zid = _create(client, admin)["id"]
    gone, _ = await make_user(sessions, "gone@railtech.uz", ["viewer"])
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE users SET is_active = false WHERE id = :i"), {"i": gone.id}
        )
    url = f"{ZONES}/{zid}"
    assert client.patch(url, json={"responsible_user_id": 99999}, headers=admin).status_code == 422
    assert (
        client.patch(url, json={"responsible_user_id": gone.id}, headers=admin).status_code == 422
    )
    same = staff["manager"][0]
    both = {"responsible_user_id": same, "deputy_user_id": same}
    assert client.patch(url, json=both, headers=admin).status_code == 422
    reversed_term = {"valid_from": "2026-12-01", "valid_to": "2026-11-01"}
    assert client.patch(url, json=reversed_term, headers=admin).status_code == 422


# --- проблемы по фактам ------------------------------------------------------------------------


async def test_problems_follow_the_facts(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    staff: dict[str, tuple[int, dict[str, str]]],
) -> None:
    admin = staff["admin"][1]
    manager_id = staff["manager"][0]
    zone = _create(client, admin, sections=["eds.visa.legal"])
    zid = zone["id"]
    url = f"{ZONES}/{zid}"
    assert _codes(zone) == ["no_responsible"]

    # Менеджер без раздела зоны: предупреждение с недостающими разделами, не запрет.
    patched = client.patch(url, json={"responsible_user_id": manager_id}, headers=admin)
    assert patched.status_code == 200, patched.text
    lacking = patched.json()["problems"]
    assert [(p["code"], p["severity"], p["sections"]) for p in lacking] == [
        ("responsible_lacks_permissions", "warning", ["eds.visa.legal"])
    ]
    # Администратор раздела «Виза юриста» не держит; директор — тоже: отвечает «Право» без прав.
    cleared = client.patch(url, json={"responsible_user_id": None}, headers=admin).json()
    assert _codes(cleared) == ["no_responsible"]

    # Зона без разделов: у ответственного прав проверять нечего.
    other = _create(client, admin, code="open_zone", sections=["crm.clients"])
    ok = client.patch(
        f"{ZONES}/{other['id']}", json={"responsible_user_id": staff["director"][0]}, headers=admin
    ).json()
    assert ok["problems"] == []

    # Замещающий отключён: проблема появляется, как только он перестал быть действующим.
    deputy_id = staff["admin"][0]
    client.patch(f"{ZONES}/{other['id']}", json={"deputy_user_id": deputy_id}, headers=admin)
    async with sessions() as session, session.begin():
        await session.execute(
            text("UPDATE users SET is_active = false WHERE id = :i"), {"i": deputy_id}
        )
    states = {z["code"]: z for z in client.get(ZONES, headers=staff["director"][1]).json()["items"]}
    assert _codes(states["open_zone"]) == ["deputy_inactive"]

    # Срок вышел.
    yesterday = (date.today() - timedelta(days=2)).isoformat()
    expired = client.patch(
        f"{ZONES}/{other['id']}",
        json={"deputy_user_id": None, "valid_to": yesterday},
        headers=staff["director"][1],
    ).json()
    assert _codes(expired) == ["term_expired"]


async def test_deactivated_zone_keeps_its_data_and_reports_nothing(
    client: TestClient, staff: dict[str, tuple[int, dict[str, str]]]
) -> None:
    admin = staff["admin"][1]
    zid = _create(client, admin)["id"]
    off = client.post(f"{ZONES}/{zid}/deactivate", headers=admin).json()
    assert (off["is_active"], off["problems"], off["code"]) == (False, [], "quality")
    assert client.patch(f"{ZONES}/{zid}", json={"basis": "x"}, headers=admin).status_code == 409
    on = client.post(f"{ZONES}/{zid}/activate", headers=admin).json()
    assert on["is_active"] is True
    assert client.get(f"{ZONES}/999999", headers=admin).status_code == 404


# --- журнал -------------------------------------------------------------------------------------


async def test_every_change_is_journaled_with_before_and_after(
    client: TestClient,
    sessions: async_sessionmaker[AsyncSession],
    staff: dict[str, tuple[int, dict[str, str]]],
) -> None:
    admin_id, admin = staff["admin"]
    director_id, director = staff["director"]
    zid = _create(client, admin)["id"]
    client.patch(
        f"{ZONES}/{zid}",
        json={"responsible_user_id": director_id, "basis": "Приказ № 5 от 01.12.2026"},
        headers=director,
    )
    client.patch(f"{ZONES}/{zid}", json={"basis": "Приказ № 5 от 01.12.2026"}, headers=director)
    client.post(f"{ZONES}/{zid}/deactivate", headers=admin)

    created = await audit_rows(sessions, "responsibility_zone.create")
    assert [(r.actor_user_id, r.entity_id) for r in created] == [(admin_id, str(zid))]
    updated = await audit_rows(sessions, "responsibility_zone.update")
    # Повтор того же значения журнал не засоряет.
    assert len(updated) == 1
    row = updated[0]
    assert row.actor_user_id == director_id
    assert row.before is not None
    assert row.after is not None
    assert (row.before["responsible_user_id"], row.after["responsible_user_id"]) == (
        None,
        director_id,
    )
    assert row.after["basis"] == "Приказ № 5 от 01.12.2026"
    off = await audit_rows(sessions, "responsibility_zone.deactivate")
    assert off[0].before is not None
    assert off[0].before["is_active"] is True

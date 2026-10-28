"""Сотрудники по разделу каталога: `GET /team?section=&level=` (D1-8, B-007) на настоящем Postgres.

Выбор исполнителя зоны резолюции и виз: активные сотрудники, у которых объединение матриц ролей
даёт раздел на уровне. Отдаются только id, имя, инициалы и должность. Право — чтение сотрудников
(`users:read`, раздел `admin` не ниже чтения); `GET /team` без параметров — прежний список «кому
передать лида» (`leads:read`).
"""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.main import create_app
from app.models.auth import User
from app.repositories import platform_roles as prepo
from app.security.audit import Actor
from app.services.user_views import UserPatch
from app.services.users import UserService
from tests.integration.crm_helpers import PASSWORD, login, make_user

pytestmark = pytest.mark.integration


@pytest.fixture
def client(
    sessions: async_sessionmaker[AsyncSession], live_settings: Settings
) -> Iterator[TestClient]:
    with TestClient(create_app(live_settings)) as test_client:
        yield test_client


async def staff(
    sessions: async_sessionmaker[AsyncSession],
    email: str,
    name: str,
    codes: list[str],
    position: str | None = None,
) -> int:
    """Сотрудник с ролями каталога по кодам (`ADMIN`, `tpl:SUPPLY`, ...), пароль сменён."""
    account, _ = await make_user(sessions, email, ["viewer"])
    async with sessions() as session:
        ids = [r.id for r in await prepo.by_codes(session, codes)]
    await UserService(sessions).update(
        Actor.system(),
        account.id,
        UserPatch(platform_role_ids=ids, full_name=name, position=position),
    )
    return account.id


@pytest.fixture
async def team(sessions: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    return {
        "director": await staff(sessions, "dir@railtech.uz", "Рустам Директоров", ["DIRECTOR"]),
        "admin": await staff(sessions, "adm@railtech.uz", "Админ Админов", ["ADMIN"]),
        "manager": await staff(
            sessions, "man@railtech.uz", "Алия Каримова", ["tpl:MANAGER"], "Менеджер"
        ),
        "supply": await staff(
            sessions, "sup@railtech.uz", "Сардор Снабженцев", ["tpl:SUPPLY"], "Снабженец"
        ),
        "engineer": await staff(sessions, "eng@railtech.uz", "Ильдар Инженеров", ["tpl:ENGINEER"]),
        "accountant": await staff(
            sessions, "acc@railtech.uz", "Бахтиёр Бухгалтеров", ["tpl:ACCOUNTANT"], "Бухгалтер"
        ),
        "both": await staff(
            sessions, "both@railtech.uz", "Универсал Двоякин", ["tpl:SUPPLY", "tpl:ACCOUNTANT"]
        ),
    }


def ask(client: TestClient, who: str, query: str = "") -> Any:
    return client.get(f"/api/v1/team{query}", headers=login(client, who, PASSWORD))


def names(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [m["full_name"] for m in response.json()]


async def test_zone_sections_list_their_holders_at_full(
    client: TestClient, team: dict[str, int]
) -> None:
    goods = ask(client, "dir@railtech.uz", "?section=erp.calc.goods&level=full")
    services = ask(client, "dir@railtech.uz", "?section=erp.calc.services&level=full")
    payments = ask(client, "dir@railtech.uz", "?section=eds.payments&level=full")

    assert names(goods) == ["Рустам Директоров", "Сардор Снабженцев", "Универсал Двоякин"]
    assert names(services) == ["Ильдар Инженеров", "Рустам Директоров"]
    # D2-4: директор читает «Счета и оплаты» (read), оплату ведёт бухгалтер — на full его нет
    assert names(payments) == ["Бахтиёр Бухгалтеров", "Универсал Двоякин"]


async def test_read_level_includes_full_and_full_excludes_read_only_holders(
    client: TestClient, team: dict[str, int]
) -> None:
    """У менеджера `eds.payments` — чтение: на уровне `read` он есть, на `full` — нет."""
    read = ask(client, "dir@railtech.uz", "?section=eds.payments&level=read")
    full = ask(client, "dir@railtech.uz", "?section=eds.payments&level=full")

    assert "Алия Каримова" in names(read)
    assert {"Бахтиёр Бухгалтеров", "Рустам Директоров"} <= set(names(read))
    assert "Алия Каримова" not in names(full)


async def test_reply_has_only_id_name_initials_and_position(
    client: TestClient, team: dict[str, int]
) -> None:
    body = ask(client, "dir@railtech.uz", "?section=eds.payments&level=full").json()

    accountant = next(m for m in body if m["id"] == team["accountant"])
    assert accountant == {
        "id": team["accountant"],
        "full_name": "Бахтиёр Бухгалтеров",
        "initials": "ББ",
        "position": "Бухгалтер",
    }
    assert team["director"] not in {m["id"] for m in body}, "директор на уровне full не числится"
    on_read = ask(client, "dir@railtech.uz", "?section=eds.payments&level=read").json()
    director = next(m for m in on_read if m["id"] == team["director"])
    assert director["position"] is None
    assert "@" not in str(body), "почты нет"
    for member in body:
        assert set(member) == {"id", "full_name", "initials", "position"}


async def test_inactive_and_legacy_only_staff_are_not_listed(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], team: dict[str, int]
) -> None:
    await make_user(sessions, "legacy@railtech.uz", ["manager"])  # базовая роль без ролей Платформы
    async with sessions() as session, session.begin():
        await session.execute(update(User).where(User.id == team["supply"]).values(is_active=False))

    goods = names(ask(client, "dir@railtech.uz", "?section=erp.calc.goods&level=full"))

    assert goods == [
        "Рустам Директоров",
        "Универсал Двоякин",
    ]  # без отключённого снабженца и legacy
    legacy = names(ask(client, "dir@railtech.uz", "?section=crm.leads&level=read"))
    assert "legacy" not in legacy


async def test_changing_a_role_changes_the_list(
    client: TestClient, sessions: async_sessionmaker[AsyncSession], team: dict[str, int]
) -> None:
    async with sessions() as session:
        (director,) = await prepo.by_codes(session, ["DIRECTOR"])
    await UserService(sessions).update(
        Actor.system(), team["supply"], UserPatch(platform_role_ids=[director.id])
    )

    services = names(ask(client, "dir@railtech.uz", "?section=erp.calc.services&level=full"))

    assert "Сардор Снабженцев" in services  # директорская роль держит все три раздела зон


@pytest.mark.parametrize("who", ["dir@railtech.uz", "adm@railtech.uz"])
async def test_staff_directory_readers_may_ask(
    client: TestClient, team: dict[str, int], who: str
) -> None:
    """Чтение сотрудников по каталогу — `admin` не ниже чтения: директор и администратор."""
    assert ask(client, who, "?section=eds.payments&level=full").status_code == 200


@pytest.mark.parametrize(
    "who", ["man@railtech.uz", "sup@railtech.uz", "eng@railtech.uz", "acc@railtech.uz"]
)
async def test_others_get_403_by_section(
    client: TestClient, team: dict[str, int], who: str
) -> None:
    response = ask(client, who, "?section=eds.payments&level=full")

    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


async def test_unauthenticated_gets_401(client: TestClient, team: dict[str, int]) -> None:
    assert client.get("/api/v1/team?section=eds.payments&level=full").status_code == 401


@pytest.mark.parametrize(
    "query",
    [
        "?section=erp.nonexistent&level=full",  # раздела нет в каталоге
        "?section=erp.calc.goods",  # уровень обязателен
        "?level=full",  # уровень без раздела
        "?section=erp.calc.goods&level=hidden",  # скрытый — не уровень
        "?section=erp.calc.goods&level=",
    ],
)
async def test_bad_query_is_422(client: TestClient, team: dict[str, int], query: str) -> None:
    response = ask(client, "dir@railtech.uz", query)

    assert response.status_code == 422, response.text


async def test_without_parameters_it_is_still_the_list_for_handing_over_a_lead(
    client: TestClient, team: dict[str, int]
) -> None:
    """Прежнее поведение: менеджеры и админы (базовая роль — признак «ведёт лидов»), `leads:read`.
    Бухгалтера и снабженца в списке нет: признак `manager` ставит матрица (`crm.leads: full`)."""
    listed = names(ask(client, "man@railtech.uz"))

    assert set(listed) == {"Админ Админов", "Алия Каримова"}
    assert ask(client, "sup@railtech.uz").status_code == 403  # у снабженца нет leads:read
    body = ask(client, "man@railtech.uz").json()
    assert {m["initials"] for m in body} == {"АА", "АК"}
    assert next(m for m in body if m["full_name"] == "Алия Каримова")["position"] == "Менеджер"

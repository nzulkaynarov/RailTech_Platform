"""СУЩ-3: справочник сотрудников для ссылки «кто сделал».

Имя, должность, фото с версией; отключённый — без фото. CRM — на respx. Справочник открыт любому
сотруднику (ему нужны фото коллег в строках), почты и телефона в нём нет."""

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL

STAFF = [
    {
        "id": 7,
        "full_name": "Иван Тестов",
        "position": "Менеджер",
        "avatar_version": 1790000000,
        "is_active": True,
        "roles": ["Менеджер", 5],
    },
    {
        "id": 8,
        "full_name": "Анна Без Фото",
        "position": None,
        "avatar_version": None,
        "is_active": True,
    },
    {
        "id": 9,
        "full_name": "Ушёл Давно",
        "position": " ",
        "avatar_version": 1700000000,
        "is_active": False,
    },
    {"full_name": "битая строка"},
]


@pytest.mark.parametrize(
    "role",
    [
        "ADMIN",
        "DIRECTOR",
        "MANAGER",
        "SUPPLY",
        "ENGINEER",
        "ACCOUNTANT",
        "REGISTRAR",
        "MANAGER_ALL",
        "LAWYER",
    ],
)
async def test_any_employee_reads_the_directory(
    web: Web, be: Backends, check: ContractChecker, role: str
) -> None:
    await web.login([role])
    be.router.get(f"{CRM_URL}/api/v1/staff").mock(return_value=httpx.Response(200, json=STAFF))

    response = await web.client.get("/api/v1/staff")

    assert response.status_code == 200
    check(response, "/staff", "get")
    assert response.json()["items"] == [
        {
            "id": "7",
            "name": "Иван Тестов",
            "position": "Менеджер",
            "avatar_url": "/api/v1/staff/7/avatar?v=1790000000",
            "active": True,
            "roles": ["Менеджер"],
        },
        {
            "id": "8",
            "name": "Анна Без Фото",
            "position": None,
            "avatar_url": None,
            "active": True,
            "roles": [],
        },
        {
            "id": "9",
            "name": "Ушёл Давно",
            "position": None,
            "avatar_url": None,
            "active": False,
            "roles": [],
        },
    ]
    # Решение 10.11: имя, должность и роли — всем; почты и телефона в справочнике нет.
    keys = {"id", "name", "position", "avatar_url", "active", "roles"}
    assert all(set(item) == keys for item in response.json()["items"])


async def test_crm_down_is_503(web: Web, be: Backends) -> None:
    await web.login(["MANAGER"])
    be.router.get(f"{CRM_URL}/api/v1/staff").mock(
        return_value=httpx.Response(200, json={"oops": 1})
    )
    response = await web.client.get("/api/v1/staff")
    assert response.status_code == 503

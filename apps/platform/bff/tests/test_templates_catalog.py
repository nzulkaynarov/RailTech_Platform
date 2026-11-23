"""«Настройки · Шаблоны» (план 2.7, TPL-1): BFF собирает шаблоны ERP, EDS и CRM одним списком."""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL, ERP_URL
from tests.eds_letters_support import EdsFake

ERP = f"{ERP_URL}/api/v1"
DOCS: dict[str, Any] = {
    "results": [
        {
            "id": 5,
            "name": "Договор поставки",
            "kind_code": "CONTRACT",
            "is_sample": True,
            "is_active": True,
        },
        {
            "id": 9,
            "name": "Счёт (наш)",
            "kind_code": "INVOICE",
            "is_sample": False,
            "is_active": False,
        },
    ],
    "next": None,
}
EMAILS: dict[str, Any] = {
    "results": [
        {
            "id": 1,
            "key": "invoice_issued",
            "language": "ru",
            "subject": "Счёт выставлен",
            "is_active": True,
        },
        {"id": 2, "key": "invoice_issued", "language": "uz", "subject": "Hisob", "is_active": True},
    ],
    "next": None,
}


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    fake = EdsFake(be)
    fake.answer(
        "GET",
        "resolution-templates",
        httpx.Response(
            200,
            json={"items": [{"id": "6f1c1a52-0f6a-4f4e-9d0b-1b2c3d4e5f60", "name": "Налоговая"}]},
        ),
    )
    fake.answer(
        "GET",
        "templates",
        httpx.Response(
            200,
            json={
                "items": [
                    {
                        "id": "5d1d0e1a-0000-4000-8000-000000000001",
                        "kind": "letter",
                        "name": "Деловое письмо",
                        "languages": ["ru", "uz", "en"],
                        "origin": "builtin",
                        "active": True,
                        "updated_at": "2026-11-15T09:00:00Z",
                    }
                ]
            },
        ),
    )
    return fake


@pytest.fixture
def domains(be: Backends) -> None:
    be.router.get(f"{ERP}/crm/document-templates/").mock(
        return_value=httpx.Response(200, json=DOCS)
    )
    be.router.get(f"{ERP}/settings/email-templates/").mock(
        return_value=httpx.Response(200, json=EMAILS)
    )
    be.router.get(f"{CRM_URL}/api/v1/reply-templates").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "id": 3,
                    "title": "Приветствие",
                    "text": {"ru": "Здравствуйте", "uz": "", "en": "Hello"},
                    "updated_at": "2026-11-10T10:00:00Z",
                }
            ],
        )
    )


async def test_director_sees_all_domains_in_one_list(
    web: Web, eds: EdsFake, domains: None, check: ContractChecker
) -> None:
    assert (await web.login(["DIRECTOR", "ADMIN"])).status_code == 200
    response = await web.client.get("/api/v1/templates")
    check(response, "/templates", "get")
    items = {row["id"]: row for row in response.json()["items"]}
    # ДОК-13: «Условия КП» — настройки, а не шаблон: строки «КП» в списке нет
    assert not any(row["kind"] == "quote" for row in items.values())
    assert {k: v for k, v in items["erp.document:5"].items() if k != "updated_at"} == {
        "id": "erp.document:5",
        "kind": "contract",
        "name": "Договор поставки",
        "domain": "erp",
        "languages": ["ru"],
        "origin": "builtin",
        "active": True,
        "path": "/admin/templates?tab=documents&template=5",
    }
    assert items["erp.document:9"]["active"] is False
    assert items["erp.email:invoice_issued"]["languages"] == ["ru", "uz"]
    assert items["erp.email:invoice_issued"]["name"] == "Счёт выставлен"
    assert items["eds.resolution:6f1c1a52-0f6a-4f4e-9d0b-1b2c3d4e5f60"]["languages"] == []
    assert items["crm.reply:3"]["languages"] == ["ru", "en"]
    letter = items["eds.template:5d1d0e1a-0000-4000-8000-000000000001"]
    assert (letter["kind"], letter["languages"], letter["origin"]) == (
        "letter",
        ["ru", "uz", "en"],
        "builtin",
    )
    assert items["crm.reply:3"]["path"] == "/admin/telegram?tab=templates&template=3"


async def test_role_sees_only_its_sources(web: Web, eds: EdsFake, domains: None) -> None:
    assert (await web.login(["REGISTRAR"])).status_code == 200
    response = await web.client.get("/api/v1/templates")
    assert response.status_code == 200
    kinds = {row["kind"] for row in response.json()["items"]}
    assert kinds == {"resolution", "letter"}


async def test_director_gets_no_reply_rows_without_a_page_to_open_them(
    web: Web, eds: EdsFake, domains: None
) -> None:
    # EV-2a: «Telegram» — страница раздела admin.system; директору строк с ссылкой на неё не отдаём
    assert (await web.login(["DIRECTOR"])).status_code == 200
    response = await web.client.get("/api/v1/templates")
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()["items"]}
    assert "crm.reply:3" not in ids
    assert "erp.document:5" in ids

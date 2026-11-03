"""EDS · Шаблоны резолюций (EDS-REG, R2): разделы каталога, ids строками туда и обратно, люди —
`PersonRef` Платформы, ошибки EDS как есть. EDS — на respx."""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_letters_support import EdsFake, eds_error_body

BASE = "/api/v1/eds/resolution-templates"
TEMPLATE_ID = "6f1c1a52-0f6a-4f4e-9d0b-1b2c3d4e5f60"
EDS_TEMPLATE: dict[str, Any] = {
    "id": TEMPLATE_ID,
    "name": "Налоговая — ответ бухгалтерии",
    "scope": "personal",
    "kind": "reply",
    "text": "Подготовить ответ.",
    "responsible_type": "person",
    "responsible": {"crm_user_id": 6, "full_name": "Бахтиёр Бухгалтеров"},
    "co_executors": [{"crm_user_id": 5, "full_name": "Алия Каримова"}],
    "acquaint": [],
    "due_days": 5,
    "owner": {"crm_user_id": 3, "full_name": "Рустам Директоров"},
    "editable": True,
}
FORM: dict[str, Any] = {
    "name": "Налоговая — ответ бухгалтерии",
    "scope": "personal",
    "kind": "reply",
    "text": "Подготовить ответ.",
    "responsible_type": "person",
    "responsible_id": "6",
    "co_executor_ids": ["5", "5"],
    "acquaint_ids": [],
    "due_days": 5,
}


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    fake = EdsFake(be)
    fake.answer("GET", "resolution-templates", httpx.Response(200, json={"items": [EDS_TEMPLATE]}))
    fake.answer("POST", "resolution-templates", httpx.Response(201, json=EDS_TEMPLATE))
    fake.answer(
        "PUT", f"resolution-templates/{TEMPLATE_ID}", httpx.Response(200, json=EDS_TEMPLATE)
    )
    fake.answer("DELETE", f"resolution-templates/{TEMPLATE_ID}", httpx.Response(204))
    return fake


async def test_list_maps_people(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    for code in ("DIRECTOR", "REGISTRAR", "ADMIN"):
        assert (await web.login([code])).status_code == 200
        response = await web.client.get(BASE)
        check(response, "/eds/resolution-templates", "get")
        item = response.json()["items"][0]
        assert item["responsible"] == {"id": "6", "name": "Бахтиёр Бухгалтеров", "initials": "ББ"}
        assert item["owner"]["id"] == "3"
    assert (await web.login(["SUPPLY"])).status_code == 200
    assert (await web.client.get(BASE)).status_code == 403


async def test_save_update_delete_send_numbers_to_eds(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    assert (await web.login(["DIRECTOR"])).status_code == 200
    created = await web.send("POST", BASE, json=FORM)
    check(created, "/eds/resolution-templates", "post")
    assert created.status_code == 201
    [sent] = eds.made("POST", "resolution-templates")
    body = httpx.Response(200, content=sent.read()).json()
    assert body["responsible_crm_user_id"] == 6
    assert body["co_executor_ids"] == [5]
    updated = await web.send("PUT", f"{BASE}/{TEMPLATE_ID}", json=FORM)
    check(updated, "/eds/resolution-templates/{id}", "put")
    removed = await web.send("DELETE", f"{BASE}/{TEMPLATE_ID}")
    assert removed.status_code == 204


async def test_eds_refusal_keeps_the_reason(web: Web, eds: EdsFake) -> None:
    eds.answer(
        "POST",
        "resolution-templates",
        httpx.Response(
            403,
            json=eds_error_body(
                "FORBIDDEN",
                "Общие шаблоны ведёт администратор.",
                reason="company_template_admin_only",
            ),
        ),
    )
    assert (await web.login(["DIRECTOR"])).status_code == 200
    response = await web.send("POST", BASE, json={**FORM, "scope": "company"})
    assert response.status_code == 403
    assert response.json()["details"]["reason"] == "company_template_admin_only"


async def test_form_errors_do_not_reach_eds(web: Web, eds: EdsFake) -> None:
    assert (await web.login(["DIRECTOR"])).status_code == 200
    for patch in (
        {"kind": "approve"},
        {"due_days": 0},
        {"responsible_id": "Иванов"},
        {"name": " "},
    ):
        response = await web.send("POST", BASE, json={**FORM, **patch})
        assert response.status_code == 422, patch
    assert eds.made("POST", "resolution-templates") == []


async def test_admin_reads_staff_for_company_templates(web: Web, eds: EdsFake) -> None:
    eds.answer("GET", "employees", httpx.Response(200, json={"items": []}))
    assert (await web.login(["ADMIN"])).status_code == 200
    assert (await web.client.get("/api/v1/eds/staff")).status_code == 200

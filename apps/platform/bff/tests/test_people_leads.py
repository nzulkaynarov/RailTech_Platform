"""Органайзер · Люди: лиды (PL-1, контракт BFF, тег `chats`).

CRM — на respx; ответ сверяется со схемой platform-bff.yaml. Проверяется то, что делает BFF:
в CRM уходят только люди (статусы без `client`/`lost`, каналы без `cabinet`/`sandbox`), «закрытые»
добавляют `lost`, строка несёт компанию и признаки контактов без значений, а показ контактов
лида сначала пишется в журнал CRM (объект `lead`), без записи контактов нет.
"""

import json
from typing import Any

import httpx
import pytest
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.messages_support import lead, lead_detail

LEADS = f"{CRM_URL}/api/v1/leads"
AUDIT = f"{CRM_URL}/api/v1/audit/contact-reveal"


def _row(**over: Any) -> dict[str, Any]:
    return {
        **lead(101, escalation=None, handoff_note=None, platform_status="dialog"),
        "company_name": "ООО Ромашка",
        "has_phone": True,
        "has_email": False,
        "has_telegram": True,
        **over,
    }


async def test_list_asks_crm_only_for_people_and_maps_the_fields(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    router: respx.MockRouter = be.router
    route = router.get(LEADS).mock(
        return_value=httpx.Response(200, json={"items": [_row()], "total": 1})
    )
    response = check(await web.client.get("/api/v1/people/leads"), "/people/leads", "get")
    assert response.json()["items"] == [
        {
            "lead": "L-0101",
            "name": "Азиз Демо",
            "company": "ООО Ромашка",
            "status": "dialog",
            "channel": "telegram",
            "language": "ru",
            "assigned": None,
            "need": "Рельсы Р65, 40 т",
            "has_phone": True,
            "has_email": False,
            "has_telegram": True,
        }
    ]
    params = dict(route.calls.last.request.url.params)
    # G7: ни ставшие клиентами, ни проигранные; ни чат Cabinet, ни пробные
    assert params["platform_status"] == "new,dialog,wants_quote,no_answer"
    assert params["source"] == "telegram,web,phone,email,referral"
    assert {"client", "lost"}.isdisjoint(params["platform_status"].split(","))
    assert {"cabinet", "sandbox"}.isdisjoint(params["source"].split(","))


async def test_closed_flag_adds_lost_leads(web: Web, be: Any) -> None:
    await web.login(["DIRECTOR"])
    router: respx.MockRouter = be.router
    route = router.get(LEADS).mock(return_value=httpx.Response(200, json={"items": [], "total": 0}))
    assert (await web.client.get("/api/v1/people/leads?closed=true")).status_code == 200
    statuses = route.calls.last.request.url.params["platform_status"].split(",")
    assert "lost" in statuses
    assert "client" not in statuses


async def test_without_the_leads_section_it_is_forbidden_before_crm(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    router: respx.MockRouter = be.router
    route = router.get(LEADS).mock(return_value=httpx.Response(200, json={"items": []}))
    assert (await web.client.get("/api/v1/people/leads")).status_code == 403
    assert (
        await web.client.post(
            "/api/v1/people/leads/L-101/reveal", headers={"X-CSRF-Token": web.csrf}
        )
    ).status_code == 403
    assert route.call_count == 0


async def test_reveal_writes_journal_first_then_gives_contacts(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.get(f"{LEADS}/101").mock(
        return_value=httpx.Response(
            200,
            json=lead_detail(
                101, phone_e164="+998901112233", email="a@b.example", tg_username="aziz_demo"
            ),
        )
    )
    audit = router.post(AUDIT).mock(return_value=httpx.Response(204))
    response = await web.client.post(
        "/api/v1/people/leads/L-0101/reveal", headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code == 200, response.text
    check(response, "/people/leads/{lead}/reveal", "post")
    assert response.json() == {
        "lead": "L-0101",
        "phone": "+998901112233",
        "email": "a@b.example",
        "telegram": "@aziz_demo",
    }
    assert json.loads(audit.calls.last.request.content) == {
        "contact": "101",
        "name": "Азиз Демо",
        "kind": "lead",
    }


@pytest.mark.parametrize("failure", [httpx.Response(500), httpx.Response(200)])
async def test_no_journal_record_no_contacts(web: Web, be: Any, failure: httpx.Response) -> None:
    await web.login(["MANAGER"])
    router: respx.MockRouter = be.router
    router.get(f"{LEADS}/101").mock(
        return_value=httpx.Response(200, json=lead_detail(101, phone_e164="+998901112233"))
    )
    router.post(AUDIT).mock(return_value=failure)
    response = await web.client.post(
        "/api/v1/people/leads/L-0101/reveal", headers={"X-CSRF-Token": web.csrf}
    )
    assert response.status_code == 503
    assert "+998901112233" not in response.text

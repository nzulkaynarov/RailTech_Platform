"""Типы входящих писем (MAIL-TYPES): справочник `mail-types` у CRM, правила, действия по типу.

CRM — на respx, данные вымышленные. Права: справочник и правила — только `admin`, смена типа и
действия — первая линия (`crm.leads.triage`).
"""

from typing import Any, Literal

import httpx

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL

DICT = f"{CRM_URL}/api/v1/dictionaries"
MAIL = f"{CRM_URL}/api/v1/inbound-mail"
RULES = f"{CRM_URL}/api/v1/mail-sender-rules"
NAME = {"ru": "Жалоба", "uz": "", "en": "Complaint"}
ITEM: dict[str, Any] = {
    "code": "complaint",
    "name": NAME,
    "attrs": {"default_action": "create_lead", "color": "default", "icon": "mail"},
    "active": True,
    "position": 90,
    "used": False,
}
RULE: dict[str, Any] = {
    "id": 5,
    "pattern": "soliq.example",
    "type_code": "official",
    "created_at": "2026-11-03T10:00:00Z",
    "created_by": "Администратор",
}


def crm_error(status: int, reason: str, message: str = "x") -> httpx.Response:
    return httpx.Response(
        status, json={"code": "conflict", "message": message, "details": {"reason": reason}}
    )


async def test_admin_edits_mail_types_in_crm_with_the_dictionary_reasons(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    be.router.post(f"{DICT}/mail-types").mock(return_value=httpx.Response(201, json=ITEM))
    be.router.get(f"{DICT}/mail-types").mock(
        return_value=httpx.Response(200, json={"items": [ITEM]})
    )
    taken = be.router.patch(f"{DICT}/mail-types/complaint").mock(
        return_value=crm_error(409, "mail_type_name_taken")
    )
    in_use = be.router.delete(f"{DICT}/mail-types/complaint").mock(
        return_value=crm_error(409, "mail_type_in_use")
    )
    assert (await web.login(["ADMIN"])).status_code == 200

    created = await web.send(
        "POST",
        "/api/v1/dictionaries/mail-types",
        json={"name": NAME, "attrs": {"default_action": "create_lead"}},
    )
    check(created, "/dictionaries/{kind}", "post")
    assert created.status_code == 201
    listed = await web.client.get("/api/v1/dictionaries/mail-types")
    check(listed, "/dictionaries/{kind}", "get")
    assert listed.json()["items"][0]["attrs"]["default_action"] == "create_lead"

    rename = await web.send(
        "PATCH", "/api/v1/dictionaries/mail-types/complaint", json={"name": NAME}
    )
    assert (rename.status_code, rename.json()["details"]["reason"]) == (409, "name_taken")
    removed = await web.send("DELETE", "/api/v1/dictionaries/mail-types/complaint")
    assert (removed.status_code, removed.json()["details"]["reason"]) == (409, "value_in_use")
    assert taken.called
    assert in_use.called


async def test_first_line_reads_the_types_but_only_admin_changes_them(
    web: Web, be: Backends
) -> None:
    be.router.get(f"{DICT}/mail-types").mock(
        return_value=httpx.Response(200, json={"items": [ITEM]})
    )
    made = be.router.post(f"{DICT}/mail-types").mock(return_value=httpx.Response(201, json=ITEM))
    assert (await web.login(["REGISTRAR"])).status_code == 200
    assert (await web.client.get("/api/v1/dictionaries/mail-types")).status_code == 200
    body = {"name": NAME, "attrs": {"default_action": "create_lead"}}
    assert (await web.send("POST", "/api/v1/dictionaries/mail-types", json=body)).status_code == 403
    assert (await web.login(["SUPPLY"])).status_code == 200
    assert (await web.client.get("/api/v1/dictionaries/mail-types")).status_code == 403
    assert not made.called


async def test_rules_are_admin_only_and_created_from_a_card(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    be.router.get(RULES).mock(return_value=httpx.Response(200, json={"items": [RULE]}))
    created = be.router.post(RULES).mock(
        return_value=httpx.Response(201, json={**RULE, "applied": 3})
    )
    removed = be.router.delete(f"{RULES}/5").mock(return_value=httpx.Response(204))
    body = {"pattern": "*@soliq.example", "type_code": "official", "mail_id": 17}

    assert (await web.login(["REGISTRAR"])).status_code == 200
    assert (await web.client.get("/api/v1/mail-sender-rules")).status_code == 200
    assert (await web.send("POST", "/api/v1/mail-sender-rules", json=body)).status_code == 403
    assert (await web.send("DELETE", "/api/v1/mail-sender-rules/5")).status_code == 403
    assert not created.called

    assert (await web.login(["ADMIN"])).status_code == 200
    listed = await web.client.get("/api/v1/mail-sender-rules")
    check(listed, "/mail-sender-rules", "get")
    made = await web.send("POST", "/api/v1/mail-sender-rules", json=body)
    check(made, "/mail-sender-rules", "post")
    assert (made.status_code, made.json()["applied"]) == (201, 3)
    assert created.calls[0].request.read() == (
        b'{"pattern":"*@soliq.example","type_code":"official","mail_id":17}'
    )
    assert (await web.send("DELETE", "/api/v1/mail-sender-rules/5")).status_code == 204
    assert removed.called


async def test_rule_conflicts_are_told_in_words(web: Web, be: Backends) -> None:
    be.router.post(RULES).mock(return_value=crm_error(409, "mail_rule_exists"))
    assert (await web.login(["ADMIN"])).status_code == 200
    response = await web.send(
        "POST", "/api/v1/mail-sender-rules", json={"pattern": "soliq.example", "type_code": "spam"}
    )
    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "mail_rule_exists"
    assert response.json()["message"] == "Такое правило уже есть."


async def test_type_change_and_actions_belong_to_the_first_line(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    put = be.router.put(f"{MAIL}/17/type").mock(return_value=httpx.Response(204))
    price = be.router.post(f"{MAIL}/17/price").mock(return_value=httpx.Response(204))
    spam = be.router.post(f"{MAIL}/17/suspicious").mock(return_value=httpx.Response(204))
    hand = be.router.post(f"{MAIL}/17/handover").mock(return_value=httpx.Response(204))
    targets = be.router.get(f"{MAIL}/handover-targets").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 9, "name": "Бухгалтер Один"}]})
    )
    calls: list[tuple[Literal["POST", "PUT"], str, dict[str, Any] | None]] = [
        ("PUT", "/api/v1/inbound-mail/17/type", {"type_code": "meeting"}),
        ("POST", "/api/v1/inbound-mail/17/price", None),
        ("POST", "/api/v1/inbound-mail/17/suspicious", None),
        ("POST", "/api/v1/inbound-mail/17/handover", {"user_id": 9}),
    ]
    assert (await web.login(["MANAGER_ALL"])).status_code == 200
    for method, path, body in calls:
        assert (await web.send(method, path, json=body)).status_code == 403, path
    assert (await web.client.get("/api/v1/inbound-mail/handover-targets")).status_code == 403
    assert not any(r.called for r in (put, price, spam, hand, targets))

    assert (await web.login(["REGISTRAR"])).status_code == 200
    for method, path, body in calls:
        assert (await web.send(method, path, json=body)).status_code == 204, path
    assert put.calls[0].request.read() == b'{"type_code":"meeting"}'
    assert hand.calls[0].request.read() == b'{"user_id":9,"purpose":"payments"}'
    listed = await web.client.get("/api/v1/inbound-mail/handover-targets")
    check(listed, "/inbound-mail/handover-targets", "get")
    assert listed.json() == {"items": [{"id": 9, "name": "Бухгалтер Один"}]}
    cleared = await web.send("PUT", "/api/v1/inbound-mail/17/type", json={"type_code": None})
    assert cleared.status_code == 204
    assert put.calls[-1].request.read() == b'{"type_code":null}'


async def test_list_passes_the_type_filter_to_crm(web: Web, be: Backends) -> None:
    route = be.router.get(MAIL).mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [],
                "total": 0,
                "mailbox": {
                    "configured": True,
                    "last_poll_at": None,
                    "last_ok_at": None,
                    "last_error_kind": None,
                    "personal_label": "Лично",
                },
                "counts": {
                    "new": 0, "history": 0, "mine": 0, "in_work": 0,
                    "done": 0, "spam": 0, "all": 0, "unread_new": 0,
                },
            },
        )
    )  # fmt: skip
    assert (await web.login(["REGISTRAR"])).status_code == 200
    response = await web.client.get("/api/v1/inbound-mail", params={"type": "meeting"})
    assert response.status_code == 200
    assert route.calls[0].request.url.params["type"] == "meeting"
    bad = await web.client.get("/api/v1/inbound-mail", params={"type": "Bad Code!"})
    assert bad.status_code == 422


async def test_price_handover_asks_crm_for_price_candidates(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    targets = be.router.get(f"{MAIL}/handover-targets").mock(
        return_value=httpx.Response(200, json={"items": [{"id": 4, "name": "Снабженец Демо"}]})
    )
    hand = be.router.post(f"{MAIL}/17/handover").mock(return_value=httpx.Response(204))
    assert (await web.login(["REGISTRAR"])).status_code == 200
    listed = await web.client.get(
        "/api/v1/inbound-mail/handover-targets", params={"purpose": "price"}
    )
    check(listed, "/inbound-mail/handover-targets", "get")
    assert targets.calls[0].request.url.params["purpose"] == "price"
    sent = await web.send(
        "POST", "/api/v1/inbound-mail/17/handover", json={"user_id": 4, "purpose": "price"}
    )
    assert sent.status_code == 204
    assert hand.calls[0].request.read() == b'{"user_id":4,"purpose":"price"}'
    bad = await web.client.get("/api/v1/inbound-mail/handover-targets", params={"purpose": "x"})
    assert bad.status_code == 422


async def test_rule_on_a_public_domain_comes_back_with_a_caution(web: Web, be: Backends) -> None:
    be.router.post(RULES).mock(
        return_value=httpx.Response(
            201, json={**RULE, "pattern": "gmail.com", "applied": 0, "caution": "public_domain"}
        )
    )
    assert (await web.login(["ADMIN"])).status_code == 200
    response = await web.send(
        "POST", "/api/v1/mail-sender-rules", json={"pattern": "gmail.com", "type_code": "spam"}
    )
    assert (response.status_code, response.json()["caution"]) == (201, "public_domain")

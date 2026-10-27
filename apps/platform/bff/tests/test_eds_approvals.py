"""EDS · КП на одобрение и документы на согласовании (контракт BFF 0.24.0, D1-4).

EDS и ERP — на respx (`eds_approvals_support`), ответы BFF проверяются по схемам platform-bff.yaml.
Проверяется то, что делает BFF: разделы каталога (КП — `eds.drafts`, служебки — `eds.memo.approve`
и чтение `eds.memo.create`; роль без раздела — 403 до EDS), токен доступа EDS из обмена токена CRM,
адресация по id и по номеру, состав КП и контакт клиента из ERP с частичным ответом `sources`,
себестоимость и маржа только с группой `cost_margin` (негативный тест), перевод ошибок решения EDS.
Решения (чек-лист, права шага, статусы) принимает EDS.
"""

import json
from typing import Any
from urllib.parse import quote

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_approvals_support import (
    MEMO_DOC,
    MEMO_NUMBER,
    MEMO_ROUTE,
    QUOTE_NUMBER,
    QUOTE_ROUTE,
    QUOTE_ROUTE_OLD,
    ApprovalsFake,
    checklist_green,
    erp_contact,
    erp_quote,
    memo_doc,
    memo_route,
    quote_route,
    step,
)
from tests.roles import Role, custom

BASE = "/api/v1/eds"
QUOTE = f"{BASE}/quotes/{QUOTE_ROUTE}"
MEMO = f"{BASE}/memo-approvals/{MEMO_DOC}"


@pytest.fixture
def eds(be: Backends) -> ApprovalsFake:
    return ApprovalsFake(be)


async def _director(web: Web) -> None:
    assert (await web.login(["DIRECTOR"])).status_code == 200


def _red(*codes: str) -> list[dict[str, Any]]:
    """Чек-лист, где перечисленные строки красные."""
    return [{**c, "ok": False} if c["code"] in codes else c for c in checklist_green()]


# --- КП: список ----------------------------------------------------------------------------------


async def test_quote_list_maps_rows_with_snapshot_and_the_eds_token(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/quotes", params=[("limit", 20)])

    check(response, "/eds/quotes", "get")
    assert response.json() == {
        "items": [
            {
                "id": QUOTE_ROUTE,
                "number": QUOTE_NUMBER,
                "version": 2,
                "request_number": "ЗВ-2026-104",
                "client_name": "ООО «Демо-Рейл»",
                "total": {"amount": "125000000.00", "currency": "UZS"},
                "due": "2026-10-29",
                "status": "open",
                "can_decide": True,
                "outgoing_number": None,
                "created_at": "2026-10-28T08:56:00Z",
            }
        ],
        "next_cursor": None,
    }
    [call] = eds.made("GET", "approvals")
    assert call.url.params["mine"] == "true"
    assert call.url.params.get_list("template") == ["quote"]
    assert call.url.params["limit"] == "20"
    assert call.headers["authorization"] == "Bearer eds-access-1"
    assert eds.sso_auds == ["erp", "eds"]


async def test_manager_sees_all_quotes_without_snapshot_data(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    """EDS не отдаёт снимок КП тому, кто не решает шаг: клиент и сумма в списке пусты."""
    eds.routes[QUOTE_ROUTE] = quote_route(quote=None, can_decide=False, allowed_decisions=[])
    assert (await web.login(["MANAGER"])).status_code == 200

    response = await web.client.get(
        f"{BASE}/quotes", params=[("scope", "all"), ("status", "open"), ("status", "approved")]
    )

    check(response, "/eds/quotes", "get")
    [row] = response.json()["items"]
    assert row["client_name"] is None
    assert row["total"] is None
    assert row["can_decide"] is False
    [call] = eds.made("GET", "approvals")
    assert call.url.params["mine"] == "false"
    assert call.url.params.get_list("status") == ["open", "approved"]


@pytest.mark.parametrize("roles", [["ADMIN"], ["SUPPLY"], ["ENGINEER"], ["ACCOUNTANT"]])
async def test_roles_without_the_drafts_section_get_403_before_eds(
    web: Web, eds: ApprovalsFake, roles: list[Role]
) -> None:
    assert (await web.login(roles)).status_code == 200
    for method, url, body in (
        ("GET", f"{BASE}/quotes", None),
        ("GET", QUOTE, None),
        ("POST", f"{QUOTE}/decision", {"decision": "approve"}),
    ):
        response = (
            await web.client.get(url) if method == "GET" else await web.send("POST", url, json=body)
        )
        assert response.status_code == 403, url
        assert response.json()["details"]["resource"] == "eds.drafts"
    assert eds.calls == []
    assert eds.exchange.call_count == 0


async def test_manager_cannot_decide_a_quote(web: Web, eds: ApprovalsFake) -> None:
    assert (await web.login(["MANAGER"])).status_code == 200

    response = await web.send("POST", f"{QUOTE}/decision", json={"decision": "approve"})

    assert response.status_code == 403
    assert response.json()["details"] == {"resource": "eds.drafts", "need": "full"}
    assert eds.made("POST", f"approvals/{QUOTE_ROUTE}/decision") == []


async def test_quote_routes_need_a_session(web: Web, eds: ApprovalsFake) -> None:
    for url in (f"{BASE}/quotes", QUOTE, f"{BASE}/memo-approvals", MEMO):
        assert (await web.client.get(url)).status_code == 401, url
    assert eds.calls == []


# --- КП: карточка --------------------------------------------------------------------------------


async def test_quote_card_collects_route_erp_lines_and_the_internal_block(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    await _director(web)

    response = await web.client.get(QUOTE)

    check(response, "/eds/quotes/{ref}", "get")
    card = response.json()
    assert card["number"] == QUOTE_NUMBER
    assert card["version"] == 2
    assert card["stage"] == "QUOTE"
    assert card["can_decide"] is True
    assert card["allowed_decisions"] == ["approve", "return", "reject"]
    assert card["client_name"] == "ООО «Демо-Рейл»"
    assert card["request"] == {
        "number": "ЗВ-2026-104",
        "title": "Стрелочные приводы",
        "path": "/crm/requests?request=%D0%97%D0%92-2026-104&panel=open&tab=card",
    }
    assert card["letter"] == {"number": "ВХ-104/26", "path": "/eds/inbox/%D0%92%D0%A5-104%2F26"}
    assert card["calculated_by"] == [
        {"name": "Снабженец Демо", "zone": "goods"},
        {"name": "Инженер Демо", "zone": "services"},
    ]
    # секции и опциональные строки: секция не строка КП; опциональная помечена
    assert [(ln["position"], ln["name"]) for ln in card["lines"]] == [
        (1, "Привод стрелочный СП-6"),
        (2, "Шефмонтаж"),
    ]
    assert card["lines"][0] == {
        "position": 1,
        "name": "Привод стрелочный СП-6",
        "quantity": 12,
        "unit": "шт",
        "unit_price": "8500000.00",
        "amount": "102000000.00",
        "lead_time_days": 45,
        "optional": False,
    }
    assert card["lines"][1]["optional"] is True
    assert card["totals"] == {
        "currency": "UZS",
        "subtotal": "111607142.86",
        "vat_rate": "12",
        "vat_amount": "13392857.14",
        "total": "125000000.00",
    }
    assert card["internal"] == {
        "cost": "103000000.00",
        "margin_amount": "22000000.00",
        "margin_pct": "17.6",
        "min_margin_pct": "15",
        "payment_terms": None,
        "valid_until": "2026-11-27",
        "supplier_price_until": None,
    }
    assert [c["code"] for c in card["checklist"]] == [
        "visa_goods",
        "visa_services",
        "margin",
        "due",
    ]
    assert card["checklist"][0]["by_name"] == "Снабженец Демо"
    assert card["checklist"][2]["value"] == "17.6 % ≥ 15 %"
    assert card["checklist"][3]["blocking"] is False
    assert card["channels"] == {
        "contact_name": "Алия Демо",
        "telegram": True,
        "cabinet": True,
        "email": True,
    }
    assert card["steps"][0]["label"] == "Директор"
    assert card["sources"] == {"crm": "ok", "erp": "ok"}
    # адреса и идентификаторы контакта наружу не уходят
    assert "aliya@example.org" not in response.text
    assert "9001" not in response.text
    assert eds.erp_paths == ["/api/v1/crm/quotes/1203/", "/api/v1/accounts/contacts/77/"]


@pytest.mark.parametrize(
    "ref", [QUOTE_NUMBER, quote(QUOTE_NUMBER, safe="")], ids=["slash", "encoded"]
)
async def test_quote_card_by_number_picks_the_open_version(
    web: Web, eds: ApprovalsFake, check: ContractChecker, ref: str
) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/quotes/{ref}")

    check(response, "/eds/quotes/{ref}", "get")
    assert response.json()["id"] == QUOTE_ROUTE
    [reg] = eds.made("GET", "registry")
    assert reg.url.params["number"] == QUOTE_NUMBER
    assert reg.url.params["kind"] == "quote"


async def test_quote_card_by_number_falls_back_to_the_latest_version(
    web: Web, eds: ApprovalsFake
) -> None:
    eds.registry[1]["status"] = "approved"
    await _director(web)

    response = await web.client.get(f"{BASE}/quotes/{quote(QUOTE_NUMBER, safe='')}")

    assert response.status_code == 200
    assert response.json()["id"] == QUOTE_ROUTE


@pytest.mark.parametrize("ref", ["КП-2026/999", "ВХ-104/26", "garbage"])
async def test_unknown_quote_number_is_404(web: Web, eds: ApprovalsFake, ref: str) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/quotes/{quote(ref, safe='')}")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


async def test_a_memo_route_is_not_a_quote(web: Web, eds: ApprovalsFake) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/quotes/{MEMO_ROUTE}")

    assert response.status_code == 404


async def test_manager_card_has_no_internal_block_and_no_margin_value(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    """Менеджер видит КП и чек-лист, но не себестоимость и маржу; кнопок решения нет."""
    eds.routes[QUOTE_ROUTE] = quote_route(quote=None, can_decide=False, allowed_decisions=[])
    assert (await web.login(["MANAGER"])).status_code == 200

    response = await web.client.get(QUOTE)

    check(response, "/eds/quotes/{ref}", "get")
    card = response.json()
    assert "internal" not in card
    assert "value" not in card["checklist"][2]
    assert card["can_decide"] is False
    assert card["allowed_decisions"] == []
    assert card["lines"] is not None
    assert "103000000" not in response.text


async def test_cost_and_margin_are_cut_without_the_cost_margin_group(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    """Негативный тест: EDS отдал экономику, а у роли нет `cost_margin` — в ответе её нет."""
    role = custom(92, "Директор без маржи", {"eds.drafts": "full"})
    assert (await web.login([role])).status_code == 200

    response = await web.client.get(QUOTE)

    check(response, "/eds/quotes/{ref}", "get")
    card = response.json()
    assert "internal" not in card
    assert all("value" not in c for c in card["checklist"] if c["code"] == "margin")
    for secret in ("103000000", "22000000", "17.6", "min_margin"):
        assert secret not in response.text, secret
    # состав и итоги без экономики остаются
    assert card["totals"]["total"] == "125000000.00"
    assert "landed_cost" not in response.text
    # а с группой — есть
    with_group = custom(93, "Директор с маржой", {"eds.drafts": "full"}, fields=("cost_margin",))
    assert (await web.login([with_group])).status_code == 200
    assert (await web.client.get(QUOTE)).json()["internal"]["cost"] == "103000000.00"


async def test_card_without_erp_is_partial(web: Web, eds: ApprovalsFake) -> None:
    eds.erp_quote = httpx.ConnectError("down")
    eds.erp_contact = httpx.ConnectError("down")
    eds.deal = httpx.ConnectError("down")
    await _director(web)

    response = await web.client.get(QUOTE)

    assert response.status_code == 200
    card = response.json()
    assert card["lines"] is None
    assert card["totals"] is None
    assert card["channels"] is None
    assert card["request"]["title"] is None
    assert card["client_name"] == "ООО «Демо-Рейл»"  # из снимка
    assert card["sources"]["erp"] == "unavailable"
    assert card["internal"]["margin_pct"] == "17.6"
    assert card["allowed_decisions"] == ["approve", "return", "reject"]


async def test_card_when_erp_refuses_the_quote(web: Web, eds: ApprovalsFake) -> None:
    eds.erp_quote = 403
    await _director(web)

    response = await web.client.get(QUOTE)

    assert response.status_code == 200
    assert response.json()["lines"] is None
    assert response.json()["sources"]["erp"] == "ok"


async def test_contact_without_email_or_cabinet(web: Web, eds: ApprovalsFake) -> None:
    eds.erp_contact = erp_contact(email="", telegram_user_id=None, company_is_registered=False)
    await _director(web)

    channels = (await web.client.get(QUOTE)).json()["channels"]

    assert channels == {
        "contact_name": "Алия Демо",
        "telegram": False,
        "cabinet": False,
        "email": False,
    }


async def test_quote_stage_follows_the_deal(web: Web, eds: ApprovalsFake) -> None:
    await _director(web)
    for stage, expected in (
        ("CONTRACT_SIGNED", "CONTRACT"),
        ("CLOSED_LOST", "LOST"),
        ("SOURCING", "QUOTE"),
    ):
        eds.deal = {**eds.deal, "stage_code": stage}  # type: ignore[dict-item]
        assert (await web.client.get(QUOTE)).json()["stage"] == expected


async def test_red_blocking_rows_come_from_eds_and_the_due_row_only_warns(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    """BFF не решает: чек-лист и `allowed_decisions` — как у EDS; «срок» только предупреждает."""
    eds.routes[QUOTE_ROUTE] = quote_route(
        checklist=_red("visa_services", "due"), allowed_decisions=["return", "reject"]
    )
    await _director(web)

    card = (await web.client.get(QUOTE)).json()

    assert card["allowed_decisions"] == ["return", "reject"]
    red = [(c["code"], c["blocking"]) for c in card["checklist"] if not c["ok"]]
    assert red == [("visa_services", True), ("due", False)]


async def test_card_shows_the_snapshot_total_and_no_mismatch_when_erp_agrees(
    web: Web, eds: ApprovalsFake
) -> None:
    await _director(web)

    card = (await web.client.get(QUOTE)).json()

    assert card["snapshot_total"] == {"amount": "125000000.00", "currency": "UZS"}
    assert card["totals_mismatch"] is False


async def test_card_flags_a_total_that_differs_from_the_snapshot(
    web: Web, eds: ApprovalsFake
) -> None:
    eds.erp_quote = erp_quote(total_incl_vat="126000000.00")
    await _director(web)

    card = (await web.client.get(QUOTE)).json()

    assert card["totals"]["total"] == "126000000.00"
    assert card["snapshot_total"]["amount"] == "125000000.00"
    assert card["totals_mismatch"] is True


async def test_another_erp_revision_hides_the_lines_of_a_closed_round(
    web: Web, eds: ApprovalsFake
) -> None:
    """У ERP уже версия 3, а круг — версии 2: строки ERP не показываем, остаётся снимок EDS."""
    eds.erp_quote = erp_quote(version=3)
    eds.routes[QUOTE_ROUTE] = quote_route(status="returned", can_decide=False, allowed_decisions=[])
    await _director(web)

    card = (await web.client.get(QUOTE)).json()

    assert card["lines"] is None
    assert card["totals"] is None
    assert card["totals_mismatch"] is False
    assert card["snapshot_total"]["amount"] == "125000000.00"
    assert card["sources"]["erp"] == "ok"


async def test_same_erp_revision_keeps_the_lines(web: Web, eds: ApprovalsFake) -> None:
    eds.erp_quote = erp_quote(version=2)
    await _director(web)

    assert (await web.client.get(QUOTE)).json()["lines"] is not None


async def test_manager_without_erp_access_gets_a_card_without_lines(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    """ERP отказал роли в КП (403): карточка 200 без строк и итогов, снимка у менеджера нет."""
    eds.routes[QUOTE_ROUTE] = quote_route(quote=None, can_decide=False, allowed_decisions=[])
    eds.erp_quote = 403
    assert (await web.login(["MANAGER"])).status_code == 200

    response = await web.client.get(QUOTE)

    check(response, "/eds/quotes/{ref}", "get")
    card = response.json()
    assert card["lines"] is None
    assert card["totals"] is None
    assert card["snapshot_total"] is None
    assert card["totals_mismatch"] is False
    assert card["checklist"][0]["code"] == "visa_goods"


async def test_supplier_prices_from_erp_never_reach_the_card(web: Web, eds: ApprovalsFake) -> None:
    """Негативный тест: ERP отдал цену и оффер поставщика — в карточке их нет ни у одной роли."""
    items = erp_quote()["items"]
    items[1].update(
        offer=77,
        offer_supplier_name="ООО «Секретный Поставщик»",
        supplier_price="6500000.00",
        purchase_price="6400000.00",
        unit_cost="6300000.00",
        frozen_base_price="6200000.00",
    )
    eds.erp_quote = erp_quote(items=items, cost_price="1", gross_profit="2", landed_cost="3")
    cases: list[list[Role]] = [["DIRECTOR"], [custom(95, "Директор", {"eds.drafts": "full"})]]
    for roles in cases:
        assert (await web.login(roles)).status_code == 200

        response = await web.client.get(QUOTE)

        assert response.status_code == 200
        for secret in (
            "Секретный Поставщик",
            "6500000",
            "6400000",
            "6300000",
            "6200000",
            '"supplier_price"',
            "purchase_price",
            "unit_cost",
            '"offer"',
        ):
            assert secret not in response.text, secret


# --- КП: решения ---------------------------------------------------------------------------------


async def test_approve_sends_channels_and_returns_the_updated_card(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    await _director(web)

    response = await web.send(
        "POST",
        f"{QUOTE}/decision",
        json={"decision": "approve", "channels": ["telegram", "cabinet", "telegram"]},
    )

    check(response, "/eds/quotes/{id}/decision", "post")
    card = response.json()
    assert card["status"] == "approved"
    assert card["outgoing_number"] == "ИСХ-031/26"
    assert card["allowed_decisions"] == []
    [call] = eds.made("POST", f"approvals/{QUOTE_ROUTE}/decision")
    assert json.loads(call.content) == {"decision": "approve", "channels": ["telegram", "cabinet"]}
    assert call.headers["authorization"] == "Bearer eds-access-1"


async def test_approve_without_channels_sends_none(web: Web, eds: ApprovalsFake) -> None:
    await _director(web)

    response = await web.send("POST", f"{QUOTE}/decision", json={"decision": "approve"})

    assert response.status_code == 200
    [call] = eds.made("POST", f"approvals/{QUOTE_ROUTE}/decision")
    assert json.loads(call.content) == {"decision": "approve"}


async def test_return_and_reject_need_a_comment_before_eds(web: Web, eds: ApprovalsFake) -> None:
    await _director(web)
    for decision in ("return", "reject"):
        for body in ({"decision": decision}, {"decision": decision, "comment": "   "}):
            response = await web.send("POST", f"{QUOTE}/decision", json=body)
            assert response.status_code == 422, body
            assert response.json()["code"] == "VALIDATION_FAILED"
    assert eds.made("POST", f"approvals/{QUOTE_ROUTE}/decision") == []

    ok = await web.send(
        "POST",
        f"{QUOTE}/decision",
        json={"decision": "return", "comment": "  Пересчитать доставку  "},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] == "returned"
    [call] = eds.made("POST", f"approvals/{QUOTE_ROUTE}/decision")
    assert json.loads(call.content) == {"decision": "return", "comment": "Пересчитать доставку"}


async def test_channels_are_for_approve_only(web: Web, eds: ApprovalsFake) -> None:
    await _director(web)

    response = await web.send(
        "POST",
        f"{QUOTE}/decision",
        json={"decision": "reject", "comment": "x", "channels": ["email"]},
    )

    assert response.status_code == 422
    assert eds.calls == []


async def test_approve_with_a_red_checklist_is_409_with_failed_codes(
    web: Web, eds: ApprovalsFake
) -> None:
    eds.routes[QUOTE_ROUTE] = quote_route(checklist=_red("visa_goods", "margin"))
    await _director(web)

    response = await web.send("POST", f"{QUOTE}/decision", json={"decision": "approve"})

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CONFLICT"
    assert body["source"] == "eds"
    assert body["details"]["reason"] == "checklist_not_green"
    assert body["details"]["failed"] == ["visa_goods", "margin"]


async def test_late_quote_is_approved_with_a_mark(web: Web, eds: ApprovalsFake) -> None:
    """Красная строка «срок» не блокирует (C1-G-1); отметку «с опозданием» ставит EDS."""
    eds.routes[QUOTE_ROUTE] = quote_route(checklist=_red("due"))
    eds.answer(
        "POST",
        f"approvals/{QUOTE_ROUTE}/decision",
        httpx.Response(
            200,
            json=quote_route(
                status="approved",
                approved_late=True,
                outgoing_number="ИСХ-031/26",
                can_decide=False,
                allowed_decisions=[],
            ),
        ),
    )
    await _director(web)

    response = await web.send("POST", f"{QUOTE}/decision", json={"decision": "approve"})

    assert response.status_code == 200
    assert response.json()["approved_late"] is True


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [(409, "route_closed", 409), (403, "not_your_step", 403), (404, None, 404)],
)
async def test_decision_errors_keep_the_eds_reason(
    web: Web, eds: ApprovalsFake, status: int, reason: str | None, expected: int
) -> None:
    details = {"reason": reason} if reason else {}
    eds.answer(
        "POST",
        f"approvals/{QUOTE_ROUTE}/decision",
        httpx.Response(
            status,
            json={
                "code": "X",
                "message": "Решено другим директором.",
                "source": "eds",
                "details": details,
            },
        ),
    )
    await _director(web)

    response = await web.send("POST", f"{QUOTE}/decision", json={"decision": "approve"})

    assert response.status_code == expected
    body = response.json()
    assert body["source"] == "eds"
    assert body["message"] == "Решено другим директором."
    assert body["details"].get("reason") == reason


async def test_a_closed_route_cannot_be_decided_twice(web: Web, eds: ApprovalsFake) -> None:
    await _director(web)
    assert (
        await web.send("POST", f"{QUOTE}/decision", json={"decision": "approve"})
    ).status_code == 200

    again = await web.send("POST", f"{QUOTE}/decision", json={"decision": "approve"})

    assert again.status_code == 409
    assert again.json()["details"]["reason"] == "route_closed"


async def test_a_superseded_version_is_reachable_by_id(web: Web, eds: ApprovalsFake) -> None:
    eds.routes[QUOTE_ROUTE_OLD] = quote_route(
        id=QUOTE_ROUTE_OLD, status="returned", can_decide=False, allowed_decisions=[]
    )
    await _director(web)

    card = (await web.client.get(f"{BASE}/quotes/{QUOTE_ROUTE_OLD}")).json()

    assert card["status"] == "returned"
    assert card["allowed_decisions"] == []


# --- документы на согласовании -------------------------------------------------------------------


async def test_memo_list_maps_rows_from_the_approval_and_the_document(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/memo-approvals")

    check(response, "/eds/memo-approvals", "get")
    assert response.json() == {
        "items": [
            {
                "id": MEMO_DOC,
                "approval_id": MEMO_ROUTE,
                "number": MEMO_NUMBER,
                "kind": "memo",
                "subject": "Оплата аренды склада за ноябрь",
                "author": {"crm_user_id": 2, "full_name": "Менеджер Демо"},
                "amount": {"amount": "8500000.00", "currency": "UZS"},
                "due_date": "2026-10-31",
                "status": "open",
                "step_label": "Директор",
                "can_decide": True,
                "created_at": "2026-10-27T10:01:00Z",
            }
        ],
        "next_cursor": None,
    }
    [call] = eds.made("GET", "approvals")
    assert call.url.params["mine"] == "true"
    assert call.url.params.get_list("template") == ["memo", "application", "report"]


async def test_memo_list_survives_a_missing_document(web: Web, eds: ApprovalsFake) -> None:
    eds.documents.clear()
    await _director(web)

    [row] = (await web.client.get(f"{BASE}/memo-approvals")).json()["items"]

    assert row["author"] is None
    assert row["amount"] is None
    assert row["subject"] == "Оплата аренды склада за ноябрь"


async def test_author_reads_own_memos_but_cannot_decide(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    """Менеджер — автор: раздел `eds.memo.create` открывает список и карточку, решения — 403."""
    eds.routes[MEMO_ROUTE] = memo_route(can_decide=False, allowed_decisions=[])
    assert (await web.login(["MANAGER"])).status_code == 200

    listing = await web.client.get(f"{BASE}/memo-approvals", params={"scope": "all"})
    card = await web.client.get(MEMO)
    decision = await web.send(
        "POST", f"{BASE}/memo-approvals/{MEMO_ROUTE}/decision", json={"decision": "approve"}
    )

    assert listing.status_code == 200
    assert card.status_code == 200
    check(card, "/eds/memo-approvals/{ref}", "get")
    assert card.json()["can_decide"] is False
    assert decision.status_code == 403
    assert decision.json()["details"] == {"resource": "eds.memo.approve", "need": "full"}
    assert eds.made("POST", f"approvals/{MEMO_ROUTE}/decision") == []
    assert eds.made("GET", "approvals")[0].url.params["mine"] == "false"


async def test_roles_without_memo_sections_get_403_before_eds(web: Web, eds: ApprovalsFake) -> None:
    role = custom(94, "Только письма", {"eds.inbox": "full"})
    assert (await web.login([role])).status_code == 200
    for method, url in (
        ("GET", f"{BASE}/memo-approvals"),
        ("GET", MEMO),
        ("POST", f"{MEMO}/decision"),
    ):
        response = (
            await web.client.get(url)
            if method == "GET"
            else await web.send("POST", url, json={"decision": "approve"})
        )
        assert response.status_code == 403, url
    assert eds.calls == []


async def test_memo_card_by_id_collects_document_route_and_files(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    await _director(web)

    response = await web.client.get(MEMO)

    check(response, "/eds/memo-approvals/{ref}", "get")
    card = response.json()
    assert card["id"] == MEMO_DOC
    assert card["approval_id"] == MEMO_ROUTE
    assert card["number"] == MEMO_NUMBER
    assert card["kind"] == "memo"
    assert card["document_status"] == "on_approval"
    assert card["status"] == "open"
    assert card["text"].startswith("Прошу согласовать")
    assert card["author"] == {"crm_user_id": 2, "full_name": "Менеджер Демо"}
    assert card["amount"] == {"amount": "8500000.00", "currency": "UZS"}
    assert card["due_date"] == "2026-10-31"
    assert [s["label"] for s in card["steps"]] == ["Директор", "Бухгалтер"]
    assert card["files"][0]["name"] == "счёт-аренда.pdf"
    assert card["can_decide"] is True
    assert card["allowed_decisions"] == ["approve", "return", "reject"]


@pytest.mark.parametrize(
    "ref", [MEMO_NUMBER, quote(MEMO_NUMBER, safe="")], ids=["slash", "encoded"]
)
async def test_memo_card_by_number_goes_through_the_registry(
    web: Web, eds: ApprovalsFake, ref: str
) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/memo-approvals/{ref}")

    assert response.status_code == 200
    assert response.json()["id"] == MEMO_DOC
    [reg] = eds.made("GET", "registry")
    assert reg.url.params["number"] == MEMO_NUMBER


async def test_memo_card_rejects_other_kinds_and_unsent_documents(
    web: Web, eds: ApprovalsFake
) -> None:
    eds.documents[MEMO_DOC] = memo_doc(approval_id=None, status="draft")
    await _director(web)
    assert (await web.client.get(MEMO)).status_code == 404

    eds.documents[MEMO_DOC] = memo_doc(kind="letter_out")
    assert (await web.client.get(MEMO)).status_code == 404
    assert (
        await web.client.get(f"{BASE}/memo-approvals/{quote(QUOTE_NUMBER, safe='')}")
    ).status_code == 404


@pytest.mark.parametrize(
    ("decision", "status"),
    [("approve", "approved"), ("return", "returned"), ("reject", "rejected")],
)
async def test_memo_decisions_return_the_updated_card(
    web: Web, eds: ApprovalsFake, check: ContractChecker, decision: str, status: str
) -> None:
    await _director(web)
    body: dict[str, Any] = {"decision": decision}
    if decision != "approve":
        body["comment"] = "Нужен счёт на бланке"

    response = await web.send("POST", f"{BASE}/memo-approvals/{MEMO_ROUTE}/decision", json=body)

    check(response, "/eds/memo-approvals/{id}/decision", "post")
    assert response.json()["status"] == status
    assert response.json()["can_decide"] is False
    [call] = eds.made("POST", f"approvals/{MEMO_ROUTE}/decision")
    assert json.loads(call.content) == body


async def test_memo_return_and_reject_need_a_comment_before_eds(
    web: Web, eds: ApprovalsFake
) -> None:
    await _director(web)
    for decision in ("return", "reject"):
        response = await web.send(
            "POST", f"{BASE}/memo-approvals/{MEMO_ROUTE}/decision", json={"decision": decision}
        )
        assert response.status_code == 422
    assert eds.made("POST", f"approvals/{MEMO_ROUTE}/decision") == []


async def test_memo_conflict_is_reported_in_words_of_eds(web: Web, eds: ApprovalsFake) -> None:
    eds.routes[MEMO_ROUTE] = memo_route(status="approved")
    await _director(web)

    response = await web.send(
        "POST", f"{BASE}/memo-approvals/{MEMO_ROUTE}/decision", json={"decision": "approve"}
    )

    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "route_closed"


async def test_memo_list_can_decide_comes_from_the_eds_route(web: Web, eds: ApprovalsFake) -> None:
    """BFF не вычисляет `can_decide` по `scope`: слово EDS по маршруту; не прочитан — `false`."""
    eds.routes[MEMO_ROUTE] = memo_route(can_decide=False, allowed_decisions=[])
    await _director(web)

    [row] = (await web.client.get(f"{BASE}/memo-approvals")).json()["items"]
    assert row["can_decide"] is False

    eds.answer(
        "GET",
        f"approvals/{MEMO_ROUTE}",
        httpx.Response(404, json={"code": "NOT_FOUND", "message": "x"}),
    )
    [row] = (await web.client.get(f"{BASE}/memo-approvals")).json()["items"]
    assert row["can_decide"] is False


def _accountant_route(**over: Any) -> dict[str, Any]:
    return memo_route(
        steps=[
            step(
                1,
                "Директор",
                "approved",
                assignee={"crm_user_id": None, "permission": "approvals.decide"},
            ),
            step(
                2,
                "Бухгалтер",
                "current",
                assignee={"crm_user_id": None, "permission": "payments.confirm"},
            ),
        ],
        **over,
    )


async def test_accountant_decides_the_memo_on_his_step(
    web: Web, eds: ApprovalsFake, check: ContractChecker
) -> None:
    """Шаг бухгалтера (`payments.confirm`): раздел `eds.payments` — полный; чей шаг, решает EDS."""
    eds.routes[MEMO_ROUTE] = _accountant_route()
    eds.documents[MEMO_DOC] = memo_doc(status="to_accountant")
    assert (await web.login(["ACCOUNTANT"])).status_code == 200

    listing = await web.client.get(f"{BASE}/memo-approvals")
    card = await web.client.get(MEMO)
    decision = await web.send(
        "POST", f"{BASE}/memo-approvals/{MEMO_ROUTE}/decision", json={"decision": "approve"}
    )

    assert listing.status_code == 200
    assert listing.json()["items"][0]["step_label"] == "Бухгалтер"
    check(card, "/eds/memo-approvals/{ref}", "get")
    assert card.json()["accountant_step"] is True
    assert card.json()["can_decide"] is True
    check(decision, "/eds/memo-approvals/{id}/decision", "post")
    assert decision.status_code == 200
    assert eds.made("POST", f"approvals/{MEMO_ROUTE}/decision")


async def test_director_step_is_not_an_accountant_step(web: Web, eds: ApprovalsFake) -> None:
    await _director(web)

    assert (await web.client.get(MEMO)).json()["accountant_step"] is False


async def test_not_your_step_for_the_accountant_comes_from_eds(
    web: Web, eds: ApprovalsFake
) -> None:
    """Бухгалтер до своей очереди: раздел пропускает, EDS отвечает 403 `not_your_step`."""
    eds.answer(
        "POST",
        f"approvals/{MEMO_ROUTE}/decision",
        httpx.Response(
            403,
            json={
                "code": "FORBIDDEN",
                "message": "Не ваш шаг.",
                "source": "eds",
                "details": {"reason": "not_your_step"},
            },
        ),
    )
    assert (await web.login(["ACCOUNTANT"])).status_code == 200

    response = await web.send(
        "POST", f"{BASE}/memo-approvals/{MEMO_ROUTE}/decision", json={"decision": "approve"}
    )

    assert response.status_code == 403
    assert response.json()["details"]["reason"] == "not_your_step"


# --- общее ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("failure", ["denied", "not_provisioned"])
async def test_eds_not_granted(web: Web, eds: ApprovalsFake, failure: str) -> None:
    if failure == "denied":
        eds.sso_status = 403
    else:
        eds.exchange_status = 403
    await _director(web)

    for url in (f"{BASE}/quotes", QUOTE, f"{BASE}/memo-approvals", MEMO):
        response = await web.client.get(url)
        assert response.status_code == 403, url
        assert response.json()["details"] == {"reason": "eds_not_granted"}
    response = await web.send("POST", f"{QUOTE}/decision", json={"decision": "approve"})
    assert response.json()["details"] == {"reason": "eds_not_granted"}
    assert (await web.client.get("/api/v1/me")).status_code == 200


@pytest.mark.parametrize("status", [500, 503])
async def test_eds_down_is_503(web: Web, eds: ApprovalsFake, status: int) -> None:
    eds.answer("GET", "approvals", httpx.Response(status, text="boom"))
    await _director(web)

    for url in (f"{BASE}/quotes", f"{BASE}/memo-approvals"):
        response = await web.client.get(url)
        assert response.status_code == 503, url
        assert response.json()["code"] == "BACKEND_UNAVAILABLE"
        assert response.json()["source"] == "eds"
    assert (await web.client.get("/api/v1/me")).status_code == 200

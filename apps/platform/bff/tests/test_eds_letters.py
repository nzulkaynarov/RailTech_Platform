"""EDS · Входящие письма и резолюция директора (контракт BFF 0.16.0, D1-3).

EDS, ERP и справочник CRM — на respx (`eds_letters_support`), ответы BFF проверяются по схемам
platform-bff.yaml. Проверяется то, что делает BFF: раздел `eds.inbox` (чтение — список и карточка,
полный — решения; роль без раздела — 403 до EDS), токен доступа EDS из обмена токена CRM `aud=eds`,
адресация письма по id и по номеру, шаг пути заявки и данные заявки из ERP с частичным ответом
`sources`, маржа только с группой `cost_margin`, перевод ошибок EDS в `Error`, кандидаты в
исполнители по разделам каталога, вложение потоком. Решения (статусы, срок, исполнители) — в EDS.
"""

import json
from typing import Any
from urllib.parse import quote

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.eds_letters_support import (
    FILE_ID,
    LETTER_ID,
    NUMBER,
    CrmDirectory,
    EdsFake,
    crm_role,
    crm_user,
    deal,
    eds_error_body,
    letter,
    resolved,
    row,
)
from tests.roles import Role, custom

BASE = "/api/v1/eds"
CARD = f"{BASE}/letters/{LETTER_ID}"


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    return EdsFake(be)


@pytest.fixture
def directory(be: Backends) -> CrmDirectory:
    return CrmDirectory(be)


async def _director(web: Web) -> None:
    assert (await web.login(["DIRECTOR"])).status_code == 200


# --- список --------------------------------------------------------------------------------------


async def test_list_maps_rows_and_passes_filters_with_the_eds_token(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    eds.page = {
        "items": [row(), row(id="2" * 8 + LETTER_ID[8:], due="2026-10-30")],
        "next_cursor": "c2",
    }
    await _director(web)

    response = await web.client.get(
        f"{BASE}/letters",
        params=[
            ("status", "awaiting_resolution"),
            ("status", "returned"),
            ("q", " стрелочные "),
            ("limit", 20),
        ],
    )

    check(response, "/eds/letters", "get")
    body = response.json()
    assert body["next_cursor"] == "c2"
    assert body["items"][0] == {
        "id": LETTER_ID,
        "number": NUMBER,
        "subject": "Запрос коммерческого предложения на стрелочные приводы",
        "client_name": "ООО «Демо-Рейл»",
        "request_number": "ЗВ-2026-104",
        "received_at": "2026-10-24",
        "status": "awaiting_resolution",
        "urgent": True,
        "due": None,
    }
    assert body["items"][1]["due"] == "2026-10-30"
    [call] = eds.made("GET", "letters")
    assert call.url.params.get_list("status") == ["awaiting_resolution", "returned"]
    assert call.url.params["q"] == "стрелочные"
    assert call.url.params["limit"] == "20"
    # токен доступа EDS — из обмена SSO-токена CRM `aud=eds`; токен CRM в EDS не уходит
    assert call.headers["authorization"] == "Bearer eds-access-1"
    assert json.loads(eds.exchange.calls.last.request.content) == {"token": "sso-eds-2"}
    assert eds.sso_auds == ["erp", "eds"]


@pytest.mark.parametrize("roles", [["DIRECTOR"], ["MANAGER"], ["ACCOUNTANT"]])
async def test_list_and_card_are_open_to_read_roles(
    web: Web, eds: EdsFake, check: ContractChecker, roles: list[Role]
) -> None:
    assert (await web.login(roles)).status_code == 200

    assert (await web.client.get(f"{BASE}/letters")).status_code == 200
    card = await web.client.get(CARD)
    assert card.status_code == 200
    check(card, "/eds/letters/{ref}", "get")


@pytest.mark.parametrize("roles", [["ADMIN"], ["SUPPLY"], ["ENGINEER"]])
async def test_roles_without_the_inbox_section_get_403_before_eds(
    web: Web, eds: EdsFake, roles: list[Role]
) -> None:
    assert (await web.login(roles)).status_code == 200
    calls: list[tuple[str, str, Any]] = [
        ("GET", f"{BASE}/letters", None),
        ("GET", CARD, None),
        ("GET", f"{BASE}/letter-files/{FILE_ID}", None),
        ("GET", f"{BASE}/resolution/assignees", None),
        ("POST", f"{CARD}/resolution", {}),
        ("POST", f"{CARD}/return", {"comment": "x"}),
        ("POST", f"{CARD}/reject", {"reason": "x"}),
    ]
    for method, url, body in calls:
        response = (
            await web.client.get(url) if method == "GET" else await web.send("POST", url, json=body)
        )
        assert response.status_code == 403, url
        assert response.json()["details"]["resource"] == "eds.inbox"
    assert eds.calls == []
    assert eds.exchange.call_count == 0


async def test_without_a_session_every_route_is_401(web: Web, eds: EdsFake) -> None:
    for url in (f"{BASE}/letters", CARD, f"{BASE}/resolution/assignees"):
        assert (await web.client.get(url)).status_code == 401, url
    assert eds.calls == []


# --- карточка ------------------------------------------------------------------------------------


async def test_card_by_id_collects_details_links_and_the_step(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await _director(web)

    response = await web.client.get(CARD)

    check(response, "/eds/letters/{ref}", "get")
    card = response.json()
    assert card["number"] == NUMBER
    assert card["status"] == "awaiting_resolution"
    assert card["stage"] == "RESOLUTION"
    assert card["lost_at_step"] is None
    assert card["sender"] == {"name": "ООО «Демо-Рейл»", "inn": "300123456", "contact": "Алия Демо"}
    assert card["sender_ref"] == {"number": "исх-27", "date": "2026-10-22"}
    assert card["addressee"] == {"id": "1", "name": "Директор Демо", "initials": "ДД"}
    assert card["manager"]["name"] == "Менеджер Демо"
    assert card["client"] == {
        "id": "42",
        "name": "ООО «Демо-Рейл»",
        "inn": "300123456",
        "path": "/crm/clients/42",
    }
    assert card["request"] == {
        "number": "ЗВ-2026-104",
        "title": "Стрелочные приводы",
        "path": "/crm/requests?request=%D0%97%D0%92-2026-104&panel=open&tab=card",
    }
    assert card["files"] == [
        {
            "id": FILE_ID,
            "name": "запрос.pdf",
            "content_type": "application/pdf",
            "size": 20480,
            "uploaded_at": "2026-10-24T09:14:00Z",
        }
    ]
    assert card["journal"][0]["action"] == "letter.registered"
    assert card["sources"] == {"crm": "ok", "erp": "ok"}
    # сделка прочитана в ERP по ссылке письма, а не по номеру
    [erp_call] = eds.erp_calls
    assert erp_call.url.path == "/api/v1/crm/deals/5/"


@pytest.mark.parametrize(
    "ref",
    [
        NUMBER,
        quote(NUMBER, safe=""),
        quote(NUMBER),
    ],
    ids=["slash", "encoded-slash", "encoded"],
)
async def test_card_by_number_goes_through_the_registry(
    web: Web, eds: EdsFake, check: ContractChecker, ref: str
) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/letters/{ref}")

    check(response, "/eds/letters/{ref}", "get")
    assert response.status_code == 200
    assert response.json()["id"] == LETTER_ID
    [lookup] = eds.made("GET", "registry")
    assert lookup.url.params["number"] == NUMBER
    assert lookup.url.params["kind"] == "letter_in"
    assert len(eds.made("GET", f"letters/{LETTER_ID}")) == 1


@pytest.mark.parametrize("ref", ["ВХ-999/26", "ЗВ-2026-104", "abc", "ВХ-104/2026", "ВХ-104/26/1"])
async def test_unknown_or_foreign_refs_are_404(web: Web, eds: EdsFake, ref: str) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/letters/{ref}")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["source"] == "eds"


async def test_unknown_id_is_404_from_eds(web: Web, eds: EdsFake) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/letters/10000000-0000-4000-8000-000000000999")

    assert response.status_code == 404
    assert response.json()["source"] == "eds"


@pytest.mark.parametrize(
    ("status", "erp_stage", "expected"),
    [
        ("awaiting_resolution", "DRAFT", ("RESOLUTION", None)),
        ("awaiting_resolution", "CLOSED_LOST", ("LOST", None)),
        ("returned", "DRAFT", ("REQUEST", None)),
        ("returned", "CLOSED_LOST", ("LOST", None)),
        ("rejected", "CLOSED_LOST", ("LOST", 2)),
        ("resolved", "DRAFT", ("CALCULATION", None)),
        ("resolved", "CALCULATING", ("CALCULATION", None)),
        ("resolved", "QUOTE_SENT", ("QUOTE", None)),
        ("resolved", "CONTRACT_SIGNED", ("CONTRACT", None)),
        ("resolved", "CLOSED_LOST", ("LOST", None)),
    ],
)
async def test_step_follows_the_letter_and_the_erp_request(
    web: Web, eds: EdsFake, status: str, erp_stage: str, expected: tuple[str, int | None]
) -> None:
    eds.letters[LETTER_ID] = resolved() if status == "resolved" else letter(status=status)
    eds.deal = deal(erp_stage)
    await _director(web)

    card = (await web.client.get(CARD)).json()

    assert (card["stage"], card["lost_at_step"]) == expected


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectError("erp down"), 500],
    ids=["network", "5xx"],
)
async def test_erp_down_gives_a_partial_card_not_an_error(
    web: Web, eds: EdsFake, check: ContractChecker, failure: Exception | int
) -> None:
    eds.letters[LETTER_ID] = resolved()
    eds.deal = failure
    await _director(web)

    response = await web.client.get(CARD)

    check(response, "/eds/letters/{ref}", "get")
    assert response.status_code == 200
    card = response.json()
    assert card["sources"] == {"crm": "ok", "erp": "unavailable"}
    assert card["stage"] == "CALCULATION"  # по самому письму: данных заявки нет
    assert card["request"]["number"] == "ЗВ-2026-104"
    assert card["request"]["title"] is None
    assert card["request"]["path"].startswith("/crm/requests?request=")
    assert card["number"] == NUMBER  # письмо показано целиком
    assert card["subject"]


async def test_request_becomes_a_project_link_after_the_contract_step(
    web: Web, eds: EdsFake
) -> None:
    eds.letters[LETTER_ID] = resolved()
    eds.deal = deal("CONTRACT_SIGNED")
    await _director(web)

    card = (await web.client.get(CARD)).json()

    assert card["stage"] == "CONTRACT"
    assert card["request"]["path"] == "/eds/projects/%D0%9F%D0%A0-2026-104?panel=open&tab=card"


async def test_letter_without_links_has_no_erp_call_and_no_blocks(web: Web, eds: EdsFake) -> None:
    eds.letters[LETTER_ID] = letter(
        links={
            "erp_request_id": None,
            "erp_deal_id": None,
            "deal_number": None,
            "crm_client_id": None,
            "erp_company_id": None,
        }
    )
    await _director(web)

    card = (await web.client.get(CARD)).json()

    assert card["client"] is None
    assert card["request"] is None
    assert card["sources"] == {"crm": "ok", "erp": "ok"}
    assert eds.erp_calls == []


async def test_manager_without_erp_access_gets_not_applicable_and_no_erp_call(
    web: Web, eds: EdsFake, be: Backends
) -> None:
    be.profile["platform_access"] = ["crm"]
    assert (await web.login(["MANAGER"])).status_code == 200

    card = (await web.client.get(CARD)).json()

    assert card["sources"]["erp"] == "not_applicable"
    assert card["request"]["title"] is None
    assert eds.erp_calls == []


async def test_erp_refusal_keeps_the_card(web: Web, eds: EdsFake) -> None:
    eds.deal = 403
    await _director(web)

    response = await web.client.get(CARD)

    assert response.status_code == 200
    assert response.json()["request"]["title"] is None


async def test_margin_is_shown_only_with_the_cost_margin_group(web: Web, eds: EdsFake) -> None:
    eds.letters[LETTER_ID] = resolved()
    await _director(web)
    director = (await web.client.get(CARD)).json()["resolution"]
    assert director["min_margin_pct"] == "15"
    assert [a["zone"] for a in director["assignees"]] == ["goods", "services"]
    assert director["assignees"][0]["person"]["name"] == "Снабженец Демо"
    assert director["decided_by"]["name"] == "Директор Демо"

    assert (await web.login(["MANAGER"])).status_code == 200
    manager = (await web.client.get(CARD)).json()["resolution"]
    assert "min_margin_pct" not in manager
    assert manager["text"] == "Посчитать с запасом по складу."

    role = custom(90, "Читатель писем", {"eds.inbox": "read"}, fields=("cost_margin",))
    assert (await web.login([role])).status_code == 200
    assert (await web.client.get(CARD)).json()["resolution"]["min_margin_pct"] == "15"


# --- решения -------------------------------------------------------------------------------------


RESOLUTION = {
    "text": "  Посчитать с запасом по складу.  ",
    "assignees": [{"id": "3", "zone": "goods"}, {"id": "4", "zone": "services"}],
    "due": "2026-10-30",
    "min_margin_pct": "15",
}


async def test_director_resolves_the_letter(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    await _director(web)

    response = await web.send("POST", f"{CARD}/resolution", json=RESOLUTION)

    check(response, "/eds/letters/{id}/resolution", "post")
    assert response.status_code == 200
    card = response.json()
    assert card["status"] == "resolved"
    assert card["stage"] == "CALCULATION"
    assert card["resolution"]["text"] == "Посчитать с запасом по складу."
    assert card["resolution"]["min_margin_pct"] == "15"
    [call] = eds.made("POST", f"letters/{LETTER_ID}/resolution")
    assert json.loads(call.content) == {
        "text": "Посчитать с запасом по складу.",
        "assignees": [{"crm_user_id": 3, "zone": "goods"}, {"crm_user_id": 4, "zone": "services"}],
        "due": "2026-10-30",
        "min_margin_pct": "15",
    }
    assert call.headers["authorization"] == "Bearer eds-access-1"


async def test_resolution_without_margin_sends_null(web: Web, eds: EdsFake) -> None:
    await _director(web)
    body = {k: v for k, v in RESOLUTION.items() if k != "min_margin_pct"}

    assert (await web.send("POST", f"{CARD}/resolution", json=body)).status_code == 200

    [call] = eds.made("POST", f"letters/{LETTER_ID}/resolution")
    assert json.loads(call.content)["min_margin_pct"] is None


async def test_margin_threshold_needs_the_cost_margin_group(web: Web, eds: EdsFake) -> None:
    """Порог маржи задаёт роль с группой `cost_margin`; остальным — 422 до EDS."""
    role = custom(91, "Директор без маржи", {"eds.inbox": "full", "admin": "read"})
    assert (await web.login([role])).status_code == 200

    response = await web.send("POST", f"{CARD}/resolution", json=RESOLUTION)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert response.json()["details"] == {
        "fields": ["min_margin_pct"],
        "reason": "margin_forbidden",
    }
    assert eds.made("POST", f"letters/{LETTER_ID}/resolution") == []

    without = {k: v for k, v in RESOLUTION.items() if k != "min_margin_pct"}
    assert (await web.send("POST", f"{CARD}/resolution", json=without)).status_code == 200
    [call] = eds.made("POST", f"letters/{LETTER_ID}/resolution")
    assert json.loads(call.content)["min_margin_pct"] is None


@pytest.mark.parametrize("roles", [["MANAGER"], ["ACCOUNTANT"]])
async def test_read_roles_cannot_decide(web: Web, eds: EdsFake, roles: list[Role]) -> None:
    assert (await web.login(roles)).status_code == 200

    for tail, body in (
        ("resolution", RESOLUTION),
        ("return", {"comment": "доработать"}),
        ("reject", {"reason": "не наш профиль"}),
    ):
        response = await web.send("POST", f"{CARD}/{tail}", json=body)
        assert response.status_code == 403, tail
        assert response.json()["code"] == "FORBIDDEN"
        assert response.json()["details"] == {"resource": "eds.inbox", "need": "full"}
    assert eds.made("POST", f"letters/{LETTER_ID}/resolution") == []
    assert eds.calls == []


async def test_decisions_need_the_csrf_token(web: Web, eds: EdsFake) -> None:
    await _director(web)

    response = await web.send("POST", f"{CARD}/return", json={"comment": "x"}, csrf="wrong")

    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert eds.calls == []


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({**RESOLUTION, "text": "   "}, "text"),
        ({**RESOLUTION, "assignees": []}, "assignees"),
        ({**RESOLUTION, "due": "завтра"}, "due"),
        ({**RESOLUTION, "min_margin_pct": "120"}, "min_margin_pct"),
        ({**RESOLUTION, "assignees": [{"id": "0", "zone": "goods"}]}, "assignees"),
        ({**RESOLUTION, "assignees": [{"id": "3", "zone": "cook"}]}, "assignees"),
    ],
)
async def test_resolution_form_errors_are_422_without_calling_eds(
    web: Web, eds: EdsFake, body: dict[str, Any], field: str
) -> None:
    await _director(web)

    response = await web.send("POST", f"{CARD}/resolution", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_FAILED"
    assert any(field in name for name in response.json()["details"]["fields"])
    assert eds.calls == []


@pytest.mark.parametrize(
    ("tail", "body"),
    [("return", {"comment": "  "}), ("reject", {"reason": ""}), ("reject", {})],
)
async def test_comment_is_required_for_return_and_reject(
    web: Web, eds: EdsFake, tail: str, body: dict[str, str]
) -> None:
    await _director(web)

    response = await web.send("POST", f"{CARD}/{tail}", json=body)

    assert response.status_code == 422
    assert eds.calls == []


async def test_return_to_manager(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    await _director(web)

    response = await web.send("POST", f"{CARD}/return", json={"comment": " Уточните объём "})

    check(response, "/eds/letters/{id}/return", "post")
    card = response.json()
    assert card["status"] == "returned"
    assert card["return_comment"] == "Уточните объём"
    assert card["stage"] == "REQUEST"
    [call] = eds.made("POST", f"letters/{LETTER_ID}/return")
    assert json.loads(call.content) == {"comment": "Уточните объём"}


async def test_reject_with_reason(web: Web, eds: EdsFake, check: ContractChecker) -> None:
    await _director(web)

    response = await web.send("POST", f"{CARD}/reject", json={"reason": "Не наш профиль"})

    check(response, "/eds/letters/{id}/reject", "post")
    card = response.json()
    assert card["status"] == "rejected"
    assert card["reject_reason"] == "Не наш профиль"
    assert (card["stage"], card["lost_at_step"]) == ("LOST", 2)
    [call] = eds.made("POST", f"letters/{LETTER_ID}/reject")
    assert json.loads(call.content) == {"reason": "Не наш профиль"}


# --- ошибки EDS в едином формате ----------------------------------------------------------------


def eds_422(*fields: tuple[str, str], message: str) -> httpx.Response:
    body = eds_error_body(
        "VALIDATION_FAILED",
        message,
        fields=[{"field": f, "message": m, "type": "value_error"} for f, m in fields],
    )
    return httpx.Response(422, json=body)


async def test_eds_422_due_in_the_past_keeps_reason_fields_and_text(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    eds.answer(
        "POST",
        f"letters/{LETTER_ID}/resolution",
        eds_422(("due", "due_in_past"), message="Срок расчёта не может быть в прошлом."),
    )
    await _director(web)

    response = await web.send(
        "POST", f"{CARD}/resolution", json={**RESOLUTION, "due": "2026-01-01"}
    )

    check(response, "/eds/letters/{id}/resolution", "post")
    assert response.status_code == 422
    assert response.json() == {
        "code": "VALIDATION_FAILED",
        "message": "Срок расчёта не может быть в прошлом.",
        "source": "eds",
        "details": {
            "backend_status": 422,
            "backend_code": "VALIDATION_FAILED",
            "fields": ["due"],
            "reason": "due_in_past",
        },
    }


async def test_eds_422_for_assignees_and_comment(web: Web, eds: EdsFake) -> None:
    eds.answer(
        "POST",
        f"letters/{LETTER_ID}/resolution",
        eds_422(
            ("assignees", "not_active_employee"), message="Исполнитель не найден или отключён."
        ),
    )
    eds.answer(
        "POST",
        f"letters/{LETTER_ID}/return",
        eds_422(
            ("body.comment", "String should have at least 1 character"), message="Проверьте поля."
        ),
    )
    await _director(web)

    one = (await web.send("POST", f"{CARD}/resolution", json=RESOLUTION)).json()
    two = (await web.send("POST", f"{CARD}/return", json={"comment": "x"})).json()

    assert one["details"]["fields"] == ["assignees"]
    assert one["details"]["reason"] == "not_active_employee"
    assert two["details"]["fields"] == ["comment"]
    assert "reason" not in two["details"]  # свободный текст ошибки разбора причиной не считается


@pytest.mark.parametrize("tail", ["resolution", "return", "reject"])
async def test_eds_409_invalid_state(
    web: Web, eds: EdsFake, check: ContractChecker, tail: str
) -> None:
    eds.answer(
        "POST",
        f"letters/{LETTER_ID}/{tail}",
        httpx.Response(
            409,
            json=eds_error_body(
                "CONFLICT",
                "Операция недоступна в текущем статусе письма.",
                reason="invalid_state",
                status="resolved",
            ),
        ),
    )
    await _director(web)
    body = {"resolution": RESOLUTION, "return": {"comment": "x"}, "reject": {"reason": "x"}}[tail]

    response = await web.send("POST", f"{CARD}/{tail}", json=body)

    check(response, f"/eds/letters/{{id}}/{tail}", "post")
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["source"] == "eds"
    assert response.json()["message"] == "Операция недоступна в текущем статусе письма."
    assert response.json()["details"]["reason"] == "invalid_state"


async def test_eds_403_from_the_domain_is_translated(web: Web, eds: EdsFake) -> None:
    eds.answer(
        "POST",
        f"letters/{LETTER_ID}/return",
        httpx.Response(
            403, json=eds_error_body("FORBIDDEN", "Нет права.", permission="letters.resolve")
        ),
    )
    await _director(web)

    response = await web.send("POST", f"{CARD}/return", json={"comment": "x"})

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["source"] == "eds"
    assert response.json()["details"]["permission"] == "letters.resolve"


@pytest.mark.parametrize("failure", ["denied", "not_provisioned"])
async def test_eds_not_granted(web: Web, eds: EdsFake, failure: str) -> None:
    """CRM не выдала токен или EDS не знает сотрудника: 403 `eds_not_granted`."""
    if failure == "denied":
        eds.sso_status = 403
    else:
        eds.exchange_status = 403
    await _director(web)

    for method, url in (("GET", f"{BASE}/letters"), ("GET", CARD), ("POST", f"{CARD}/return")):
        response = (
            await web.client.get(url)
            if method == "GET"
            else await web.send("POST", url, json={"comment": "x"})
        )
        assert response.status_code == 403, url
        body = response.json()
        assert body["code"] == "FORBIDDEN"
        assert body["source"] == "eds"
        assert body["details"] == {"reason": "eds_not_granted"}
    # сессия Платформы цела
    assert (await web.client.get("/api/v1/me")).status_code == 200


@pytest.mark.parametrize("status", [500, 502, 503])
async def test_eds_down_is_503_and_keeps_the_session(web: Web, eds: EdsFake, status: int) -> None:
    eds.answer("GET", "letters", httpx.Response(status, text="boom"))
    await _director(web)

    response = await web.client.get(f"{BASE}/letters")

    assert response.status_code == 503
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"
    assert response.json()["source"] == "eds"
    assert (await web.client.get("/api/v1/me")).status_code == 200


async def test_unreadable_eds_answer_is_503(web: Web, eds: EdsFake) -> None:
    eds.answer("GET", f"letters/{LETTER_ID}", httpx.Response(200, json={"id": LETTER_ID}))
    await _director(web)

    response = await web.client.get(CARD)

    assert response.status_code == 503
    assert response.json()["details"] == {"reason": "bad_letter"}


# --- кандидаты в исполнители ---------------------------------------------------------------------

GOODS_ROLE = crm_role(11, {"erp.calc": "full", "erp.calc.goods": "full"})
SERVICES_ROLE = crm_role(12, {"erp.calc": "full", "erp.calc.services": "full"})
PAY_ROLE = crm_role(13, {"eds.payments": "full", "eds.projects": "full"})
READ_ROLE = crm_role(14, {"erp.calc.goods": "read", "eds.payments": "read"})


async def test_candidates_come_from_catalog_sections_not_role_codes(
    web: Web, eds: EdsFake, directory: CrmDirectory, check: ContractChecker
) -> None:
    directory.roles = [GOODS_ROLE, SERVICES_ROLE, PAY_ROLE, READ_ROLE]
    directory.users = [
        crm_user(3, "Снабженец Демо", [11], position="Снабженец"),
        crm_user(4, "Инженер Демо", [12]),
        crm_user(5, "Бухгалтер Демо", [13], position="Бухгалтер"),
        crm_user(6, "Универсал Демо", [11, 12, 13]),
        crm_user(7, "Читатель Демо", [14]),
        crm_user(8, "Отключённый Демо", [11], active=False),
        crm_user(9, "Без ролей", []),
    ]
    await _director(web)

    response = await web.client.get(f"{BASE}/resolution/assignees")

    check(response, "/eds/resolution/assignees", "get")
    body = response.json()
    assert body["directory"] == "ok"
    names = {z["zone"]: [c["name"] for c in z["candidates"]] for z in body["zones"]}
    assert [z["zone"] for z in body["zones"]] == ["goods", "services", "payment_terms"]
    assert names == {
        "goods": ["Снабженец Демо", "Универсал Демо"],
        "services": ["Инженер Демо", "Универсал Демо"],
        "payment_terms": ["Бухгалтер Демо", "Универсал Демо"],
    }
    goods = body["zones"][0]["candidates"][0]
    assert goods == {"id": "3", "name": "Снабженец Демо", "initials": "СД", "position": "Снабженец"}
    assert "email" not in json.dumps(body)
    # справочник читается токеном сотрудника в CRM; EDS не нужен
    assert eds.calls == []
    assert all(c.headers["authorization"].startswith("Bearer crm-access-") for c in directory.calls)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (403, "forbidden"),
        (500, "unavailable"),
        (404, "unavailable"),
        (httpx.ConnectError("x"), "unavailable"),
    ],
)
async def test_candidates_report_why_the_directory_is_missing(
    web: Web, directory: CrmDirectory, status: int | Exception, expected: str
) -> None:
    directory.status = status
    await _director(web)

    response = await web.client.get(f"{BASE}/resolution/assignees")

    assert response.status_code == 200
    body = response.json()
    assert body["directory"] == expected
    assert [z["candidates"] for z in body["zones"]] == [[], [], []]


@pytest.mark.parametrize("roles", [["MANAGER"], ["ACCOUNTANT"]])
async def test_candidates_are_for_those_who_decide(
    web: Web, directory: CrmDirectory, roles: list[Role]
) -> None:
    assert (await web.login(roles)).status_code == 200

    response = await web.client.get(f"{BASE}/resolution/assignees")

    assert response.status_code == 403
    assert response.json()["details"] == {"resource": "eds.inbox", "need": "full"}
    assert directory.calls == []


# --- вложения ------------------------------------------------------------------------------------


@pytest.mark.parametrize("roles", [["DIRECTOR"], ["MANAGER"]])
async def test_attachment_is_streamed_as_a_download(
    web: Web, eds: EdsFake, roles: list[Role]
) -> None:
    assert (await web.login(roles)).status_code == 200

    response = await web.client.get(f"{BASE}/letter-files/{FILE_ID}")

    assert response.status_code == 200
    assert response.content == b"%PDF-1.7 demo"
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "sandbox"
    assert response.headers["cache-control"] == "private, no-store"
    [call] = eds.made("GET", f"files/{FILE_ID}")
    assert call.headers["authorization"] == "Bearer eds-access-1"


async def test_unsafe_disposition_from_eds_becomes_a_plain_attachment(
    web: Web, eds: EdsFake
) -> None:
    eds.answer(
        "GET",
        f"files/{FILE_ID}",
        httpx.Response(200, content=b"<html>", headers={"content-disposition": "inline"}),
    )
    await _director(web)

    response = await web.client.get(f"{BASE}/letter-files/{FILE_ID}")

    assert response.headers["content-disposition"] == "attachment"


async def test_missing_attachment_is_404_in_the_common_format(web: Web, eds: EdsFake) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/letter-files/40000000-0000-4000-8000-000000000009")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
    assert response.json()["source"] == "eds"


async def test_attachment_id_must_be_a_uuid(web: Web, eds: EdsFake) -> None:
    await _director(web)

    response = await web.client.get(f"{BASE}/letter-files/not-a-uuid")

    assert response.status_code == 422
    assert eds.calls == []

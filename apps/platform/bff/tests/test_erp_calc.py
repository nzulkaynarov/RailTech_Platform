"""Расчёт по заявке (D2-1, контракт 0.24.0, тег `calc`): `/erp/calc*` поверх ERP `/api/v1/calc/*`.

ERP — на respx; ответы BFF сверяются со схемами platform-bff.yaml. Решения (зона строки, визы,
«Расчёт готов») — за ERP: здесь проверяются доступ к разделам каталога (403 до ERP), поиск заявки по
номеру ЗВ, вырезание полей `cost_margin`, `totals_only`, `supplier_prices`, перевод ошибок ERP и
разбор ответа ИИ-разбора.
"""

import json
from typing import Any

import httpx
import pytest
import respx

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL

API = f"{ERP_URL}/api/v1"
CALC = f"{API}/calc"
NUMBER = "ЗВ-2026-104"
ENCODED = "%D0%97%D0%92-2026-104"


def deal(**extra: Any) -> dict[str, Any]:
    return {
        "id": 104,
        "title": "Стрелочные переводы",
        "created_at": "2026-10-20T09:00:00+05:00",
        "stage_code": "CALCULATING",
        "client_name": "ООО Пример Логистик",
        "manager_name": "Демо Менеджеров",
        **extra,
    }


def task_row(**extra: Any) -> dict[str, Any]:
    return {
        "deal": deal(),
        "letter_number": "ВХ-104/26",
        "due": "2026-10-30",
        "state": "in_progress",
        "lines": 2,
        "visas": {"stock": "none", "supply": "done", "engineer": "waiting"},
        "assignees": [
            {"crm_user_id": 11, "zone": "goods", "name": "Демо Снабженцев"},
            {"crm_user_id": 12, "zone": "services", "name": None},
        ],
        **extra,
    }


def line(**extra: Any) -> dict[str, Any]:
    return {
        "id": 7,
        "position": 1,
        "name": "Перевод стрелочный Р65 1/11",
        "article": "СП-Р65-11",
        "product_id": 3,
        "product_name": "Перевод стрелочный Р65 1/11",
        "kind": "goods_to_order",
        "zone": "goods",
        "quantity": 2,
        "unit": "шт.",
        "stock": {"on_hand": 1, "cell": None, "reserved": None},
        "supplier": {
            "name": "ООО Вымышленный Поставщик",
            "lead_days": 45,
            "min_order_qty": 1,
            "price_valid_until": "2026-12-31",
            "offer_price": "90000000.00",
            "offer_currency": "UZS",
        },
        "lead_days": 45,
        "purchase_price": "90000000.00",
        "purchase_currency": "UZS",
        "crew_rate": None,
        "crew_days": None,
        "cost": "90000000.00",
        "client_price": "99000000.00",
        "markup_pct": "10.0",
        "visa": {"by": "Демо Снабженцев", "at": "2026-10-27T10:00:00+00:00"},
        "group": "supply",
        "can_edit": True,
        **extra,
    }


def service_line() -> dict[str, Any]:
    return line(
        id=8,
        name="Монтаж стрелочного перевода",
        article="",
        product_id=None,
        product_name=None,
        kind="service",
        zone="services",
        stock={"on_hand": None, "cell": None, "reserved": None},
        supplier=None,
        lead_days=None,
        purchase_price=None,
        crew_rate="1500000.00",
        crew_days="3.0",
        cost="4500000.00",
        client_price="5400000.00",
        markup_pct="20.0",
        visa=None,
        group="engineer",
        can_edit=False,
    )


def sheet(**extra: Any) -> dict[str, Any]:
    return {
        "deal": deal(),
        "task": {
            "letter_number": "ВХ-104/26",
            "letter_subject": "Запрос КП",
            "resolution_text": "Рассчитать до пятницы, маржа не ниже 15%",
            "decided_at": "2026-10-27T06:30:00+00:00",
            "decided_by_name": "Демо Директоров",
            "due": "2026-10-30",
            "min_margin_pct": "15.00",
            "assignees": task_row()["assignees"],
        },
        "request": {"text": "Нужны 2 стрелочных перевода", "lines": 0},
        "quote": {
            "id": 5,
            "version": 1,
            "number": None,
            "state": "in_progress",
            "director_comment": None,
            "vat_rate": "12.00",
        },
        "lines": [line(), service_line()],
        "totals": {
            "purchase": "189000000.00",
            "client": "208800000.00",
            "markup_pct": "10.5",
            "vat_included": False,
        },
        "visas": {
            "stock": {"state": "none", "total": 0, "signed": 0, "by": []},
            "supply": {"state": "done", "total": 1, "signed": 1, "by": ["Демо Снабженцев"]},
            "engineer": {"state": "waiting", "total": 1, "signed": 0, "by": []},
        },
        "ready": {"allowed": False, "blocker": "visas_missing", "missing": 1},
        "rights": {"goods": True, "services": False, "build": True, "cost": True},
        **extra,
    }


@pytest.fixture
def erp(be: Backends) -> respx.MockRouter:
    """ERP: заявка с заданием расчёта в списке и в лёгком справочнике для поиска по номеру."""
    be.router.get(f"{CALC}/tasks/").mock(
        return_value=httpx.Response(200, json={"results": [task_row()]})
    )
    be.router.get(f"{CALC}/deals/").mock(return_value=httpx.Response(200, json=refs(deal())))
    return be.router


def refs(*deals: dict[str, Any]) -> dict[str, Any]:
    return {
        "results": [
            {"id": d["id"], "created_at": d["created_at"], "stage_code": d["stage_code"]}
            for d in deals
        ]
    }


def erp_data_calls(router: respx.MockRouter) -> list[Any]:
    return [
        c
        for c in router.calls
        if c.request.url.host == "erp.test" and c.request.url.path.startswith("/api/v1/calc")
    ]


async def call(web: Web, method: str, path: str, body: Any = None) -> httpx.Response:
    return await web.client.request(
        method,
        f"/api/v1{path}",
        json=body,
        headers={"X-CSRF-Token": web.csrf},
    )


# --- список ------------------------------------------------------------------------------------


async def test_requests_list(web: Web, erp: respx.MockRouter, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])

    response = await web.client.get("/api/v1/erp/calc/requests", params={"mine": "true"})

    assert response.status_code == 200
    check(response, "/erp/calc/requests", "get")
    (row,) = response.json()["items"]
    assert row["number"] == NUMBER
    assert row["path"] == f"/erp/calc/{ENCODED}"
    assert row["step"] == "CALCULATION"
    assert row["client"] == "ООО Пример Логистик"
    assert row["visas"] == {"stock": "none", "supply": "done", "engineer": "waiting"}
    assert row["responsible"] == "Демо Менеджеров"
    assert row["assignees"][1] == {"zone": "services", "name": None}
    assert erp.calls.last.request.url.params["mine"] == "1"


@pytest.mark.parametrize("role", ["MANAGER", "ADMIN"])
async def test_without_calc_section_everything_is_403_and_erp_is_untouched(
    web: Web, erp: respx.MockRouter, role: str
) -> None:
    await web.login([role])
    for method, path in (
        ("GET", "/erp/calc/requests"),
        ("GET", f"/erp/calc/{NUMBER}"),
        ("GET", "/erp/calc/catalog?q=перевод"),
        ("POST", f"/erp/calc/{NUMBER}/start"),
        ("POST", f"/erp/calc/{NUMBER}/ready"),
        ("POST", f"/erp/calc/{NUMBER}/lines/7/visa"),
        ("PATCH", f"/erp/calc/{NUMBER}/lines/7"),
    ):
        response = await call(web, method, path, {"quantity": 2} if method == "PATCH" else None)
        assert response.status_code == 403, (method, path)
    assert erp_data_calls(erp) == []


# --- экран расчёта и поля с ограничением -------------------------------------------------------


async def test_sheet_for_supply_has_cost_and_supplier_prices(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    route = erp.get(f"{CALC}/104/").mock(return_value=httpx.Response(200, json=sheet()))

    response = await web.client.get(f"/api/v1/erp/calc/{ENCODED}")

    assert response.status_code == 200, response.json()
    check(response, "/erp/calc/{number}", "get")
    body = response.json()
    assert route.called
    assert body["number"] == NUMBER
    assert body["step"] == "CALCULATION"
    assert body["task"]["min_margin_pct"] == "15.00"
    assert body["task"]["decided_by"] == "Демо Директоров"
    goods = body["lines"][0]
    assert goods["id"] == "7"
    assert goods["product_id"] == "3"
    assert goods["cost"] == "90000000.00"
    assert goods["markup_pct"] == "10.0"
    assert goods["supplier"]["offer_price"] == "90000000.00"
    assert body["totals"] == {
        "client": "208800000.00",
        "purchase": "189000000.00",
        "markup_pct": "10.5",
        "vat_included": False,
    }


async def test_engineer_sees_cost_of_services_only(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    """Q-D2-1-2: держатель зоны услуг видит себестоимость своих строк (ставка, дни), но не товаров,
    не цены поставщиков, не наценку и не итоги себестоимости."""
    await web.login(["ENGINEER"])
    erp.get(f"{CALC}/104/").mock(return_value=httpx.Response(200, json=sheet()))

    response = await web.client.get(f"/api/v1/erp/calc/{ENCODED}")

    check(response, "/erp/calc/{number}", "get")
    body = response.json()
    assert body["rights"]["cost"] is False
    goods, service = body["lines"]
    assert service["crew_rate"] == "1500000.00"
    assert service["crew_days"] == "3.0"
    assert service["cost"] == "4500000.00"
    assert "markup_pct" not in service
    text = json.dumps(goods, ensure_ascii=False)
    for key in ("purchase_price", '"cost"', "markup_pct", "offer_price"):
        assert key not in text, key
    assert "90000000" not in json.dumps(body, ensure_ascii=False)
    assert "min_margin_pct" not in body["task"]
    assert body["totals"] == {"client": "208800000.00", "vat_included": False}


async def test_accountant_sees_client_prices_and_totals_only(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    """Q-D2-1-4: бухгалтер — цены клиенту, итоги и НДС; без цен поставщика, себестоимости, маржи."""
    await web.login(["ACCOUNTANT"])
    erp.get(f"{CALC}/104/").mock(return_value=httpx.Response(200, json=sheet()))

    response = await web.client.get(f"/api/v1/erp/calc/{ENCODED}")

    check(response, "/erp/calc/{number}", "get")
    body = response.json()
    assert body["totals"] == {"client": "208800000.00", "vat_included": False}
    assert body["quote"]["vat_rate"] == "12.00"
    for line in body["lines"]:
        assert line["crew_rate"] is None
        assert line["crew_days"] is None
        for key in ("purchase_price", "cost", "markup_pct"):
            assert key not in line, key
    assert "offer_price" not in body["lines"][0]["supplier"]
    assert "1500000" not in json.dumps(body, ensure_ascii=False)


async def test_number_is_found_in_the_light_reference_of_erp(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    """Заявка по номеру — лёгкий справочник ERP (без строк и виз), и ушедшая дальше расчёта."""
    await web.login(["SUPPLY"])
    done = deal(stage_code="QUOTE_SENT")
    other = deal(id=7, created_at="2026-01-05T09:00:00+05:00")
    route = be.router.get(f"{CALC}/deals/").mock(
        return_value=httpx.Response(200, json=refs(other, done))
    )
    be.router.get(f"{CALC}/104/").mock(return_value=httpx.Response(200, json=sheet(deal=done)))

    response = await web.client.get(f"/api/v1/erp/calc/{ENCODED}")

    assert response.status_code == 200
    assert response.json()["step"] == "QUOTE"
    assert route.call_count == 1


async def test_unknown_number_is_404(web: Web, be: Backends, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    be.router.get(f"{CALC}/deals/").mock(return_value=httpx.Response(200, json={"results": []}))

    response = await web.client.get("/api/v1/erp/calc/ЗВ-2026-999")

    assert response.status_code == 404
    check(response, "/erp/calc/{number}", "get")
    assert response.json()["details"]["reason"] == "calc_task_not_found"


# --- строки, визы, «Расчёт готов» ---------------------------------------------------------------


async def test_role_without_zone_cannot_sign_or_edit_and_erp_is_untouched(
    web: Web, erp: respx.MockRouter
) -> None:
    """Бухгалтер читает расчёт (`erp.calc` — чтение), но без разделов зон строки не трогает."""
    await web.login(["ACCOUNTANT"])
    for method, path in (
        ("POST", f"/erp/calc/{NUMBER}/lines/7/visa"),
        ("PATCH", f"/erp/calc/{NUMBER}/lines/7"),
        ("DELETE", f"/erp/calc/{NUMBER}/lines/7"),
        ("POST", f"/erp/calc/{NUMBER}/lines"),
        ("POST", f"/erp/calc/{NUMBER}/ready"),
    ):
        body = (
            {"quantity": 3}
            if method == "PATCH"
            else ({"lines": [{"name": "Х"}]} if path.endswith("lines") else None)
        )
        response = await call(web, method, path, body)
        assert response.status_code == 403, (method, path)
    assert erp_data_calls(erp) == []


async def test_sign_is_proxied_and_zone_refusal_of_erp_keeps_its_reason(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    ok = erp.post(f"{CALC}/104/lines/7/visa/").mock(return_value=httpx.Response(200, json=sheet()))
    refused = erp.post(f"{CALC}/104/lines/8/visa/").mock(
        return_value=httpx.Response(403, json={"detail": "ZONE_NOT_PERMITTED", "zone": "services"})
    )

    signed = await call(web, "POST", f"/erp/calc/{ENCODED}/lines/7/visa")
    assert signed.status_code == 200
    assert ok.called
    check(signed, "/erp/calc/{number}/lines/{line_id}/visa", "post")

    denied = await call(web, "POST", f"/erp/calc/{ENCODED}/lines/8/visa")
    assert denied.status_code == 403
    assert refused.called
    check(denied, "/erp/calc/{number}/lines/{line_id}/visa", "post")
    assert denied.json()["details"]["reason"] == "zone_not_permitted"


async def test_ready_without_all_visas_is_409_from_erp(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    erp.post(f"{CALC}/104/ready/").mock(
        return_value=httpx.Response(409, json={"detail": "VISAS_MISSING", "missing": 1})
    )

    response = await call(web, "POST", f"/erp/calc/{ENCODED}/ready")

    assert response.status_code == 409
    check(response, "/erp/calc/{number}/ready", "post")
    body = response.json()
    assert body["code"] == "CONFLICT"
    assert body["details"]["reason"] == "visas_missing"
    assert body["details"]["missing"] == 1
    assert "Расчёт готов" in body["message"]


async def test_ready_sends_the_quote_to_the_director(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])
    done = sheet(
        quote={**sheet()["quote"], "state": "at_director", "number": "КП-2026/115"},
        ready={"allowed": False, "blocker": "not_draft", "missing": 0},
    )
    route = erp.post(f"{CALC}/104/ready/").mock(return_value=httpx.Response(200, json=done))

    response = await call(web, "POST", f"/erp/calc/{ENCODED}/ready")

    assert response.status_code == 200
    assert route.called
    check(response, "/erp/calc/{number}/ready", "post")
    assert response.json()["quote"] == {
        "number": "КП-2026/115",
        "version": 1,
        "state": "at_director",
        "director_comment": None,
        "vat_rate": "12.00",
    }


async def test_purchase_without_cost_margin_is_refused_in_bff(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])

    response = await call(web, "PATCH", f"/erp/calc/{ENCODED}/lines/8", {"purchase_price": "1"})

    assert response.status_code == 422
    check(response, "/erp/calc/{number}/lines/{line_id}", "patch")
    assert response.json()["details"] == {"reason": "cost_forbidden", "fields": ["purchase_price"]}
    assert erp_data_calls(erp) == []


async def test_patch_is_proxied_with_numbers_and_validation_maps_to_fields(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    route = erp.patch(f"{CALC}/104/lines/7/").mock(
        side_effect=[
            httpx.Response(200, json=sheet()),
            httpx.Response(400, json={"detail": "CLIENT_PRICE_BELOW_COST"}),
        ]
    )

    ok = await call(
        web,
        "PATCH",
        f"/erp/calc/{ENCODED}/lines/7",
        {"product_id": "3", "client_price": "99000000"},
    )
    assert ok.status_code == 200
    assert json.loads(route.calls[0].request.content) == {
        "product_id": 3,
        "client_price": "99000000",
    }

    bad = await call(web, "PATCH", f"/erp/calc/{ENCODED}/lines/7", {"client_price": "1"})
    assert bad.status_code == 422
    check(bad, "/erp/calc/{number}/lines/{line_id}", "patch")
    assert bad.json()["details"]["fields"] == ["client_price"]
    assert bad.json()["details"]["reason"] == "client_price_below_cost"


async def test_free_service_line_needs_services_section(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    denied = await call(
        web, "POST", f"/erp/calc/{ENCODED}/lines", {"lines": [{"name": "ПНР", "kind": "service"}]}
    )
    assert denied.status_code == 403
    assert denied.json()["details"] == {"resource": "erp.calc.services", "need": "full"}
    assert erp_data_calls(erp) == []

    route = erp.post(f"{CALC}/104/lines/").mock(return_value=httpx.Response(201, json=sheet()))
    added = await call(
        web, "POST", f"/erp/calc/{ENCODED}/lines", {"lines": [{"name": "Болт М24", "quantity": 4}]}
    )
    assert added.status_code == 200
    check(added, "/erp/calc/{number}/lines", "post")
    assert json.loads(route.calls.last.request.content) == {
        "lines": [{"name": "Болт М24", "quantity": 4}]
    }


# --- ИИ-разбор и каталог -----------------------------------------------------------------------


async def test_parse_returns_job_and_result_is_a_proposal(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    erp.post(f"{CALC}/104/parse/").mock(return_value=httpx.Response(202, json={"task_id": "job-1"}))
    status = erp.get(f"{API}/sourcing/ai-status/job-1/").mock(
        side_effect=[
            httpx.Response(200, json={"task_id": "job-1", "status": "PENDING", "result": None}),
            httpx.Response(
                200,
                json={
                    "task_id": "job-1",
                    "status": "SUCCESS",
                    "result": {
                        "proposal": [
                            {
                                "name": "Перевод Р65",
                                "quantity": 2,
                                "unit": "шт.",
                                "article": "",
                                "note": "",
                            }
                        ],
                        "recognized": 1,
                        "truncated": False,
                    },
                },
            ),
            httpx.Response(
                200,
                json={
                    "task_id": "job-1",
                    "status": "SUCCESS",
                    "result": {"error": "AI_EXTRACT_FAILED"},
                },
            ),
        ]
    )

    queued = await call(web, "POST", f"/erp/calc/{ENCODED}/parse", {})
    assert queued.status_code == 202
    check(queued, "/erp/calc/{number}/parse", "post")
    assert queued.json() == {"job_id": "job-1"}

    pending = await web.client.get("/api/v1/erp/calc-jobs/job-1")
    check(pending, "/erp/calc-jobs/{job_id}", "get")
    assert pending.json() == {"status": "pending", "lines": []}
    done = await web.client.get("/api/v1/erp/calc-jobs/job-1")
    check(done, "/erp/calc-jobs/{job_id}", "get")
    assert done.json()["status"] == "done"
    assert done.json()["lines"][0]["name"] == "Перевод Р65"
    failed = await web.client.get("/api/v1/erp/calc-jobs/job-1")
    assert failed.json() == {"status": "failed", "lines": [], "reason": "ai_extract_failed"}
    assert status.call_count == 3


async def test_parse_when_ai_is_off_is_409(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    erp.post(f"{CALC}/104/parse/").mock(
        return_value=httpx.Response(409, json={"detail": "AI_DISABLED"})
    )

    response = await call(web, "POST", f"/erp/calc/{ENCODED}/parse", {})

    assert response.status_code == 409
    check(response, "/erp/calc/{number}/parse", "post")
    assert response.json()["details"]["reason"] == "ai_disabled"


async def test_foreign_parse_job_is_404(web: Web, erp: respx.MockRouter) -> None:
    await web.login(["SUPPLY"])
    erp.get(f"{API}/sourcing/ai-status/job-2/").mock(
        return_value=httpx.Response(403, json={"detail": "TASK_ACCESS_DENIED"})
    )
    assert (await web.client.get("/api/v1/erp/calc-jobs/job-2")).status_code == 404


async def test_catalog_search(web: Web, erp: respx.MockRouter, check: ContractChecker) -> None:
    await web.login(["ENGINEER"])
    erp.get(f"{CALC}/catalog/").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "id": 3,
                        "name": "Перевод стрелочный Р65 1/11",
                        "article": "СП-Р65-11",
                        "kind": "goods",
                        "on_hand": 1,
                        "supplier_name": "ООО Вымышленный Поставщик",
                        "lead_days": 45,
                    }
                ]
            },
        )
    )

    response = await web.client.get("/api/v1/erp/calc/catalog", params={"q": "Р65"})

    assert response.status_code == 200
    check(response, "/erp/calc/catalog", "get")
    assert response.json()["items"][0]["id"] == "3"
    assert erp.calls.last.request.url.params["q"] == "Р65"


async def test_ready_on_a_closed_deal_is_409_with_words(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    erp.post(f"{CALC}/104/ready/").mock(
        return_value=httpx.Response(
            409, json={"detail": "DEAL_NOT_IN_CALCULATION", "stage": "CLOSED_LOST"}
        )
    )

    response = await call(web, "POST", f"/erp/calc/{ENCODED}/ready")

    assert response.status_code == 409
    check(response, "/erp/calc/{number}/ready", "post")
    assert response.json()["details"]["reason"] == "deal_not_in_calculation"
    assert "Заявка закрыта" in response.json()["message"]


async def test_sheet_blocker_not_in_calculation_passes_through(
    web: Web, erp: respx.MockRouter, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    blocked = sheet(ready={"allowed": False, "blocker": "not_in_calculation", "missing": 0})
    erp.get(f"{CALC}/104/").mock(return_value=httpx.Response(200, json=blocked))

    response = await web.client.get(f"/api/v1/erp/calc/{ENCODED}")

    check(response, "/erp/calc/{number}", "get")
    assert response.json()["ready"]["blocker"] == "not_in_calculation"

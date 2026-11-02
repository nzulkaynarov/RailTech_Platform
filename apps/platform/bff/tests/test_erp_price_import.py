"""CAT-1 (L0-2): поставщик, цена поставщика, загрузка прайса, изменения карточки от поставщиков,
публикация.

ERP — на respx; ответы BFF проверяются по схемам platform-bff.yaml. Решения (права, правило
«чужие карточки не перезаписываются», отчёт) — за ERP; здесь: раздел `erp.stock`, поле
`supplier_prices` до обращения в ERP, передача параметров загрузки адресом и файла — как есть,
перевод отчёта и состояния загрузки, коды отказов ERP. Названия заводов вымышлены.
"""

import json
from typing import Any

import httpx
import respx

from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.test_erp_catalog import ITEM_DETAIL, OFFER, SUPPLIER, call, erp_data_calls, mock

API = f"{ERP_URL}/api/v1"
SUPPLIER_DETAIL = {
    **SUPPLIER,
    "id": 12,
    "name": "Werk Nordlicht GmbH",
    "tin": "",
    "registration_number": "HRB 000001",
    "country": "Германия",
    "country_id": 7,
    "currency": "EUR",
    "is_manufacturer": True,
    "contact_person": "Отдел продаж",
    "phone": "",
    "email": "sales@nordlicht.example",
    "website": "",
    "legal_address": "",
    "offers": [],
    "prices_visible": True,
    "brands": [],
    "manufactured_brands": [{"id": 2, "name": "Nordlicht"}],
}
REPORT = {
    "status": "success",
    "dry_run": True,
    "created": 1,
    "updated": 1,
    "offers_upserted": 2,
    "offers_created": 1,
    "offers_updated": 1,
    "proposal_count": 1,
    "proposals": [
        {
            "row": 3,
            "product_id": 4,
            "product_name": "Вентиль запорный ВЗ-50",
            "field": "name",
            "current": "Вентиль запорный ВЗ-50",
            "proposed": "Клапан AQ-50",
        }
    ],
    "skipped": 1,
    "error_count": 1,
    "errors": [{"row": 4, "message": "UNKNOWN_CURRENCY:XYZ"}],
    "warning_count": 0,
    "warnings": [],
    "rows_truncated": 0,
    "unpublishable": 1,
    "missing_breakdown": [],
    "items_processed": 2,
}


def body_of(route: respx.Route) -> Any:
    return json.loads(route.calls.last.request.content)


# --- поставщик ----------------------------------------------------------------------------------


async def test_supplier_create_and_update_go_to_erp_with_ids(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    created = (
        mock(be)
        .post(f"{API}/catalog/suppliers/")
        .mock(return_value=httpx.Response(201, json=SUPPLIER_DETAIL))
    )
    response = await call(
        web,
        "POST",
        "/erp/catalog/suppliers",
        {
            "name": "Werk Nordlicht GmbH",
            "country_id": "7",
            "registration_number": "HRB 000001",
            "currency": "EUR",
            "is_manufacturer": True,
        },
    )
    assert response.status_code == 201, response.text
    check(response, "/erp/catalog/suppliers", "post")
    assert body_of(created) == {
        "name": "Werk Nordlicht GmbH",
        "country_id": 7,
        "registration_number": "HRB 000001",
        "currency": "EUR",
        "is_manufacturer": True,
    }
    assert response.json()["registration_number"] == "HRB 000001"
    assert response.json()["manufactured_brands"] == [{"id": "2", "name": "Nordlicht"}]

    mock(be).patch(f"{API}/catalog/suppliers/12/").mock(
        return_value=httpx.Response(200, json=SUPPLIER_DETAIL)
    )
    updated = await call(web, "PATCH", "/erp/catalog/suppliers/12", {"phone": "+49 000"})
    assert updated.status_code == 200
    check(updated, "/erp/catalog/suppliers/{id}", "patch")


async def test_duplicate_supplier_and_missing_id_are_explained(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = mock(be).post(f"{API}/catalog/suppliers/")
    route.mock(return_value=httpx.Response(409, json={"detail": "SUPPLIER_EXISTS"}))
    conflict = await call(
        web, "POST", "/erp/catalog/suppliers", {"name": "Завод", "tin": "301234567"}
    )
    assert conflict.status_code == 409
    assert conflict.json()["details"]["reason"] == "supplier_exists"

    route.mock(return_value=httpx.Response(400, json={"detail": "SUPPLIER_ID_REQUIRED"}))
    missing = await call(web, "POST", "/erp/catalog/suppliers", {"name": "Завод"})
    assert missing.status_code == 422
    assert missing.json()["details"]["fields"] == ["tin"]


async def test_read_level_cannot_add_supplier_price_or_import(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])
    for method, path in (
        ("POST", "/erp/catalog/suppliers"),
        ("PATCH", "/erp/catalog/suppliers/12"),
        ("POST", "/erp/catalog/suppliers/12/offers"),
        ("POST", "/erp/catalog/items/4/publish"),
        ("POST", "/erp/catalog/proposals/5/accept"),
        ("POST", "/erp/catalog/price-import/apply-checked"),
    ):
        response = await call(web, method, path)
        assert response.status_code == 403, (method, path)
    assert erp_data_calls(be.router) == []


# --- цена поставщика -----------------------------------------------------------------------------


async def test_offer_create_needs_supplier_prices_before_erp(web: Web, be: Any) -> None:
    body = {
        "product_id": "4",
        "price": {"amount": "250.00", "currency": "USD"},
        "delivery_basis": "FCA",
        "valid_until": "2027-01-31",
        "source": "rfq_reply",
    }
    route = (
        mock(be)
        .post(f"{API}/catalog/suppliers/12/offers/")
        .mock(return_value=httpx.Response(201, json=OFFER))
    )
    await web.login(["ENGINEER"])  # раздел полный, но цен поставщиков не видит
    refused = await call(web, "POST", "/erp/catalog/suppliers/12/offers", body)
    assert refused.status_code == 403
    assert refused.json()["details"]["restricted"] == "supplier_prices"
    assert not route.called


async def test_offer_create_and_history(web: Web, be: Any, check: ContractChecker) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .post(f"{API}/catalog/suppliers/12/offers/")
        .mock(return_value=httpx.Response(201, json=OFFER))
    )
    created = await call(
        web,
        "POST",
        "/erp/catalog/suppliers/12/offers",
        {
            "product_id": "4",
            "price": {"amount": "250.00", "currency": "USD"},
            "delivery_basis": "FCA",
        },
    )
    assert created.status_code == 201, created.text
    check(created, "/erp/catalog/suppliers/{id}/offers", "post")
    assert body_of(route) == {
        "product_id": 4,
        "price": {"amount": "250.00", "currency": "USD"},
        "delivery_basis": "FCA",
    }
    assert created.json()["delivery_basis"] == "FCA"
    assert created.json()["source"] == "price_list"

    history = [
        {
            "at": "2026-11-02T10:00:00+05:00",
            "price": {"amount": "260.00", "currency": "USD"},
            "valid_from": None,
            "valid_until": "2027-01-31",
            "delivery_basis": "FCA",
            "source": "manual",
            "by": "Снабженец",
        }
    ]
    mock(be).get(f"{API}/catalog/suppliers/12/offers/31/history/").mock(
        return_value=httpx.Response(200, json=history)
    )
    seen = await web.client.get("/api/v1/erp/catalog/suppliers/12/offers/31/history")
    assert seen.status_code == 200
    check(seen, "/erp/catalog/suppliers/{id}/offers/{offer_id}/history", "get")
    assert seen.json()["items"][0]["price"] == {"amount": "260.00", "currency": "USD"}


async def test_offer_history_cuts_price_for_roles_without_the_field(web: Web, be: Any) -> None:
    await web.login(["ENGINEER"])
    mock(be).get(f"{API}/catalog/suppliers/12/offers/31/history/").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "at": "2026-11-02T10:00:00+05:00",
                    "price": {"amount": "260.00", "currency": "USD"},
                    "valid_from": None,
                    "valid_until": None,
                    "delivery_basis": None,
                    "source": "manual",
                    "by": None,
                }
            ],
        )
    )
    seen = await web.client.get("/api/v1/erp/catalog/suppliers/12/offers/31/history")
    assert seen.json()["items"][0]["price"] is None
    assert "260.00" not in seen.text


# --- карточка: изменения от поставщиков и публикация -------------------------------------------


async def test_accept_reject_publish_return_the_card(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    card = {
        **ITEM_DETAIL,
        "proposals_count": 1,
        "proposals": [
            {
                "id": 5,
                "field": "hs_code",
                "current": "8544",
                "proposed": "8544429007",
                "supplier": {"id": 12, "name": "Werk Nordlicht GmbH"},
                "created_at": "2026-11-02T10:00:00+05:00",
            }
        ],
    }
    router = mock(be)
    for path in (
        "catalog/field-proposals/5/accept/",
        "catalog/field-proposals/5/reject/",
        "catalog/items/4/publish/",
        "catalog/items/4/unpublish/",
    ):
        router.post(f"{API}/{path}").mock(return_value=httpx.Response(200, json=card))
    for path, template in (
        ("/erp/catalog/proposals/5/accept", "/erp/catalog/proposals/{id}/accept"),
        ("/erp/catalog/proposals/5/reject", "/erp/catalog/proposals/{id}/reject"),
        ("/erp/catalog/items/4/publish", "/erp/catalog/items/{id}/publish"),
        ("/erp/catalog/items/4/unpublish", "/erp/catalog/items/{id}/unpublish"),
    ):
        response = await call(web, "POST", path)
        assert response.status_code == 200, path
        check(response, template, "post")
    assert response.json()["proposals"][0]["supplier"]["name"] == "Werk Nordlicht GmbH"

    router.post(f"{API}/catalog/items/4/publish/").mock(
        return_value=httpx.Response(409, json={"detail": "PRODUCT_INCOMPLETE"})
    )
    incomplete = await call(web, "POST", "/erp/catalog/items/4/publish")
    assert incomplete.status_code == 409
    assert incomplete.json()["details"]["reason"] == "product_incomplete"


async def test_item_update_sends_brand_mpn_and_hs_code(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .patch(f"{API}/catalog/items/4/")
        .mock(return_value=httpx.Response(200, json=ITEM_DETAIL))
    )
    response = await call(
        web,
        "PATCH",
        "/erp/catalog/items/4",
        {"brand_id": "2", "manufacturer_part_number": "AQ-50", "hs_code": "8481806310"},
    )
    assert response.status_code == 200
    assert body_of(route) == {
        "brand_id": 2,
        "manufacturer_part_number": "AQ-50",
        "hs_code": "8481806310",
    }
    bad = await call(web, "PATCH", "/erp/catalog/items/4", {"hs_code": "12a"})
    assert bad.status_code == 422


async def test_items_list_forwards_the_pending_proposals_filter(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .get(f"{API}/catalog/items/")
        .mock(
            return_value=httpx.Response(
                200, json={"count": 0, "next": None, "previous": None, "results": []}
            )
        )
    )
    response = await web.client.get("/api/v1/erp/catalog/items", params={"proposals": "pending"})
    assert response.status_code == 200
    assert route.calls.last.request.url.params["proposals"] == "pending"


# --- загрузка прайса ----------------------------------------------------------------------------


async def test_import_passes_file_as_is_and_parameters_by_address(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .post(f"{API}/sourcing/import-catalog/")
        .mock(return_value=httpx.Response(202, json={"task_id": "abc-123"}))
    )
    response = await web.client.post(
        "/api/v1/erp/catalog/price-import",
        params={"supplier_id": "12", "valid_until": "2027-03-31"},
        files={"file": ("price.xlsx", b"PK\x03\x04xlsx", "application/octet-stream")},
        headers={"X-CSRF-Token": web.csrf},
    )
    assert response.status_code == 202, response.text
    check(response, "/erp/catalog/price-import", "post")
    assert response.json() == {"job_id": "abc-123", "mode": "xlsx"}
    request = route.calls.last.request
    assert dict(request.url.params) == {
        "supplier_company_id": "12",
        "dry_run": "true",
        "valid_until": "2027-03-31",
    }
    assert b"PK\x03\x04xlsx" in request.content


async def test_import_ai_mode_goes_to_the_ai_endpoint(web: Web, be: Any) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .post(f"{API}/sourcing/import-catalog-ai/")
        .mock(return_value=httpx.Response(202, json={"task_id": "ai-1"}))
    )
    response = await web.client.post(
        "/api/v1/erp/catalog/price-import",
        params={"supplier_id": "12", "mode": "ai", "check": "false"},
        files={"file": ("price.pdf", b"%PDF-1.4", "application/pdf")},
        headers={"X-CSRF-Token": web.csrf},
    )
    assert response.status_code == 202
    assert response.json()["mode"] == "ai"
    assert route.calls.last.request.url.params["dry_run"] == "false"


async def test_import_needs_supplier_prices_and_a_form(web: Web, be: Any) -> None:
    route = (
        mock(be)
        .post(f"{API}/sourcing/import-catalog/")
        .mock(return_value=httpx.Response(202, json={"task_id": "x"}))
    )
    await web.login(["ENGINEER"])
    refused = await web.client.post(
        "/api/v1/erp/catalog/price-import",
        params={"supplier_id": "12"},
        files={"file": ("price.xlsx", b"PK", "application/octet-stream")},
        headers={"X-CSRF-Token": web.csrf},
    )
    assert refused.status_code == 403
    await web.login(["SUPPLY"])
    not_form = await web.client.post(
        "/api/v1/erp/catalog/price-import",
        params={"supplier_id": "12"},
        content=b"{}",
        headers={"X-CSRF-Token": web.csrf, "Content-Type": "application/json"},
    )
    assert not_form.status_code == 422
    assert not route.called


async def test_import_status_translates_report_and_failures(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    router = mock(be)
    router.get(f"{API}/sourcing/import-status/abc-123/").mock(
        return_value=httpx.Response(
            200, json={"task_id": "abc-123", "status": "SUCCESS", "result": REPORT}
        )
    )
    done = await web.client.get("/api/v1/erp/catalog/price-import/abc-123")
    assert done.status_code == 200
    check(done, "/erp/catalog/price-import/{job_id}", "get")
    report = done.json()["report"]
    assert done.json()["state"] == "done"
    assert (
        report["checked"],
        report["items_created"],
        report["offers_updated"],
        report["proposal_count"],
    ) == (
        True,
        1,
        1,
        1,
    )
    assert report["errors"] == [{"row": 4, "code": "UNKNOWN_CURRENCY", "value": "XYZ"}]

    router.get(f"{API}/sourcing/import-status/run-1/").mock(
        return_value=httpx.Response(
            200, json={"task_id": "run-1", "status": "PENDING", "result": None}
        )
    )
    running = await web.client.get("/api/v1/erp/catalog/price-import/run-1")
    assert running.json() == {"state": "running", "report": None, "error": None}

    router.get(f"{API}/sourcing/ai-status/ai-1/").mock(
        return_value=httpx.Response(
            200,
            json={
                "task_id": "ai-1",
                "status": "SUCCESS",
                "result": {"status": "error", "message": "AI_EXTRACT_EMPTY"},
            },
        )
    )
    failed = await web.client.get("/api/v1/erp/catalog/price-import/ai-1", params={"mode": "ai"})
    assert failed.json() == {"state": "failed", "report": None, "error": "AI_EXTRACT_EMPTY"}


async def test_apply_checked_rows_sends_the_token(
    web: Web, be: Any, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    route = (
        mock(be)
        .post(f"{API}/sourcing/import-catalog-ai/")
        .mock(return_value=httpx.Response(202, json={"task_id": "ai-2"}))
    )
    rows_ref = "a" * 32
    response = await call(
        web,
        "POST",
        "/erp/catalog/price-import/apply-checked",
        {"supplier_id": "12", "rows_token": rows_ref},
    )
    assert response.status_code == 202
    check(response, "/erp/catalog/price-import/apply-checked", "post")
    assert dict(route.calls.last.request.url.params) == {
        "supplier_company_id": "12",
        "rows_token": rows_ref,
    }


async def test_template_is_streamed_as_an_attachment(web: Web, be: Any) -> None:
    await web.login(["MANAGER"])
    mock(be).get(f"{API}/sourcing/catalog-template/").mock(
        return_value=httpx.Response(200, content=b"PK\x03\x04tpl")
    )
    response = await web.client.get("/api/v1/erp/catalog/price-import/template")
    assert response.status_code == 200
    assert response.content == b"PK\x03\x04tpl"
    assert response.headers["content-disposition"].startswith("attachment")
    assert response.headers["x-content-type-options"] == "nosniff"

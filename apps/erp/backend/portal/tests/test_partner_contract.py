"""Сторож контракта для раздела «Мои товары» (PART-2): ответы `/partner/*` проходят JSON Schema `erp-portal.yaml`.

Те же проверки, что у `test_contract_guard.py` (схема, множество ключей ⊆ `properties`), но на мире партнёра: сессия клиента
в этот раздел не допущена. Каждое значение enum, достижимое из модели, должно встретиться в ответах.
"""

import base64
import uuid
from types import SimpleNamespace

import pytest
from portal.tests.contract_support import check_response, component, contract_get_paths, response_schema
from portal.tests.partner_world import PREFIX, row, upload, xlsx
from portal.tests.test_contract_guard import PARTNER_GET_PATHS

from sourcing.catalog_import import run_catalog_import

pytestmark = pytest.mark.django_db


def test_partner_get_paths_are_exactly_the_contract_ones():
    assert PARTNER_GET_PATHS == {path for path in contract_get_paths() if path.startswith("/partner/")}


def assert_matches(body, path, method="get", status="200"):
    problems = check_response(body, response_schema(path, method, status))
    assert not problems, f"{method.upper()} {path}: " + "; ".join(problems)


def test_list_and_detail_match_the_contract(partner_world):
    w = partner_world
    page = w["client_a"].get(f"{PREFIX}/products")
    assert page.status_code == 200
    assert_matches(page.json(), "/partner/products")
    seen_status = {item["status"] for item in page.json()["items"]}
    seen_freshness = {item["offer"]["freshness"] for item in page.json()["items"] if item["offer"]}
    assert seen_status == set(component("PartnerCardStatus")["enum"])
    assert {"fresh", "expiring"} <= seen_freshness
    for card in w["cards"].values():
        response = w["client_a"].get(f"{PREFIX}/products/{card.pk}")
        if response.status_code == 200:
            assert_matches(response.json(), "/partner/products/{id}")


def test_every_review_decision_is_reachable_in_history(partner_world):
    from catalog.models import ProductReview

    w = partner_world
    ProductReview.objects.create(product=w["cards"]["published"], decision="published")
    decisions = set()
    for card in w["cards"].values():
        response = w["client_a"].get(f"{PREFIX}/products/{card.pk}")
        if response.status_code == 200:
            decisions |= {h["decision"] for h in response.json()["history"]}
    assert decisions == {"pending", "published", "returned"}


def test_submit_and_confirm_match_the_contract(partner_world):
    w = partner_world
    c = w["cards"]
    submit = w["client_a"].post(
        f"{PREFIX}/products/submit", {"ids": [c["draft"].pk, c["b_only"].pk, c["published"].pk]}, format="json"
    )
    assert_matches(submit.json(), "/partner/products/submit", "post")
    confirm = w["client_a"].post(f"{PREFIX}/offers/confirm", {"ids": [c["draft"].pk, c["b_only"].pk]}, format="json")
    assert_matches(confirm.json(), "/partner/offers/confirm", "post")
    assert {e["code"] for e in submit.json()["errors"] + confirm.json()["errors"]} <= set(
        component("ErrorCode")["enum"]
    )


def test_price_list_task_matches_the_contract(partner_world, monkeypatch):
    w = partner_world
    results = {}

    def delay(b64, supplier_id, dry_run, **options):
        task_id = uuid.uuid4().hex
        results[task_id] = run_catalog_import(base64.b64decode(b64), supplier_id, dry_run, **options)
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr("portal.services.partner_price_list.process_catalog_import.delay", delay)
    monkeypatch.setattr(
        "portal.services.partner_price_list.async_result",
        lambda task_id: SimpleNamespace(state="SUCCESS", result=results[task_id]),
    )
    records = [
        row(),
        row(**{"Наименование": "Кран", "Артикул производителя": "K-1", "Цена": "abc"}),
        row(**{"Наименование": "Болт А-4 иначе", "Артикул производителя": "A-4"}),
        row(**{"Наименование": "Ещё одна", "Артикул производителя": "N-1", "Код ТН ВЭД": "99999999999999999999"}),
    ]
    accepted = upload(w["client_a"], xlsx(records))
    assert accepted.status_code == 202
    assert_matches(accepted.json(), "/partner/price-list", "post", "202")
    task = w["client_a"].get(f"{PREFIX}/price-list/{accepted.json()['task_id']}")
    assert_matches(task.json(), "/partner/price-list/{task_id}")
    report = task.json()["report"]
    assert report["errors"] and report["proposals"] and report["missing_breakdown"]


def test_price_template_is_a_workbook(partner_world):
    response = partner_world["client_a"].get(f"{PREFIX}/price-template")
    assert response.status_code == 200 and response.content[:2] == b"PK"
    assert "spreadsheetml" in response["Content-Type"]

"""D2-1: «Расчёт по заявке» (`/api/v1/calc/*`, `crm.services.calculation`).

Матрица ролей: снабженец (`quote.visa_goods`) правит и визирует только товарные строки, гл. инженер
(`quote.visa_services`) — только услуги (ставка бригады и дни), без права — 403; любая правка снимает визу строки;
«Расчёт готов» без всех виз — 409 `VISAS_MISSING`, со всеми — КП «На утверждении» и событие `quote.ready_for_approval`
с визами строк; себестоимость по строкам — только с `quote.view_cost_margin`; ИИ-разбор — предложение без записи.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest
from integration.models import CrmUserMapping
from integration.tests import bus_support
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from catalog.models import DomainType, Product, SupplierOffer
from crm.models import ActivityLog, CalcLine, Deal, DealStage, Quote, QuoteItem
from crm.services import calc_tasks
from master_data.models import Country, Currency

pytestmark = pytest.mark.django_db

SUPPLY = ["quote.build", "quote.edit_pricing", "quote.view_cost_margin", "quote.visa_goods", "deal.manage"]
ENGINEER = ["quote.build", "quote.edit_pricing", "quote.visa_services", "deal.manage"]


def _user(email, crm_user_id=None):
    user = CustomUser.objects.create_user(
        email=email, username=email, password="pw", is_active=True, first_name=email.split("@")[0].title()
    )
    if crm_user_id is not None:
        CrmUserMapping.objects.create(crm_user_id=crm_user_id, user=user)
    return user


def _staff(seller, email, permissions, crm_user_id=None):
    role = CompanyRole.objects.create(company=seller, name=f"Роль {email}", permissions=list(permissions))
    user = _user(email, crm_user_id)
    CompanyMember.objects.create(
        user=user,
        company=seller,
        role=WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "MEMBER", "sort_order": 10})[0],
        company_roles=[role],
        is_primary=True,
        is_active=True,
        can_sell=False,
    )
    return user


def _api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def world(db):
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "sort_order": 10})
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[
        0
    ]
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})[0]
    seller = Company.objects.create(name="ООО Демо Рейл", inn="7700000201")
    seller.types.add(supplier_type)
    vendor = Company.objects.create(name="ООО Вымышленный Поставщик", inn="7700000202")
    vendor.types.add(supplier_type)
    supply = _staff(seller, "supply@demo.test", SUPPLY, crm_user_id=11)
    engineer = _staff(seller, "engineer@demo.test", ENGINEER, crm_user_id=12)
    accountant = _staff(seller, "accountant@demo.test", [])
    client = Company.objects.create(name="ООО Пример Логистик", inn="6600000201")
    client.types.add(client_type)
    deal = Deal.objects.create(
        title="Стрелочные переводы",
        company=client,
        manager=supply,
        stage=DealStage.objects.get(code="RFQ_OPEN"),
        notes="Нужны 2 стрелочных перевода Р65 и монтаж бригадой",
    )
    calc_tasks.apply_resolution(
        deal,
        eds_letter_id=uuid.UUID("0b1f5c0e-9a51-4c43-8a0e-3c1f0a2d5e01"),
        letter_number="ВХ-104/26",
        letter_subject="Запрос КП",
        text="Рассчитать до пятницы, маржа не ниже 15%",
        due=date(2026, 10, 30),
        min_margin_pct=Decimal("15"),
        decided_by_crm_user_id=3,
        decided_by_name="Демо Директоров",
        decided_at=datetime(2026, 10, 27, 6, 30, tzinfo=timezone.utc),
        assignees=[calc_tasks.Assignment(11, "goods"), calc_tasks.Assignment(12, "services")],
    )
    services = DomainType.objects.get_or_create(code="SERVICES", defaults={"name": "Услуги", "sort_order": 20})[0]
    rail = Product.objects.create(name="Перевод стрелочный Р65 1/11", manufacturer_part_number="СП-Р65-11")
    SupplierOffer.objects.create(product=rail, supplier=seller, base_price=Decimal("0"), stock_quantity=1)
    SupplierOffer.objects.create(
        product=rail,
        supplier=vendor,
        base_price=Decimal("90000000.00"),
        min_order_qty=1,
        order_lead_time_days=45,
        valid_until=date(2026, 12, 31),
    )
    mounting = Product.objects.create(name="Монтаж стрелочного перевода", domain_type=services)
    return {
        "seller": seller,
        "supply": supply,
        "engineer": engineer,
        "accountant": accountant,
        "deal": deal,
        "rail": rail,
        "mounting": mounting,
    }


def _url(world, suffix=""):
    return f"/api/v1/calc/{world['deal'].pk}/{suffix}"


def _started(world):
    """Начатый расчёт: товар (перевод, под заказ) и услуга (монтаж)."""
    response = _api(world["supply"]).post(_url(world, "start/"))
    assert response.status_code == 200, response.json()
    goods = _api(world["supply"]).post(
        _url(world, "lines/"), {"lines": [{"product_id": world["rail"].pk, "quantity": 2}]}, format="json"
    )
    assert goods.status_code == 201, goods.json()
    service = _api(world["engineer"]).post(
        _url(world, "lines/"), {"lines": [{"product_id": world["mounting"].pk, "quantity": 2}]}, format="json"
    )
    assert service.status_code == 201, service.json()
    lines = {line["zone"]: line for line in service.json()["lines"]}
    return lines["goods"]["id"], lines["services"]["id"]


def _sheet(world, user):
    response = _api(user).get(_url(world))
    assert response.status_code == 200, response.json()
    return response.json()


# ── список ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_tasks_list_shows_due_visas_and_assignees(world):
    response = _api(world["accountant"]).get("/api/v1/calc/tasks/")
    assert response.status_code == 200
    (row,) = response.json()["results"]
    assert row["deal"]["id"] == world["deal"].pk and row["deal"]["client_name"] == "ООО Пример Логистик"
    assert row["deal"]["stage_code"] == "CALCULATING", "резолюция перевела заявку в расчёт"
    assert row["letter_number"] == "ВХ-104/26" and row["due"] == "2026-10-30"
    assert row["state"] == "not_started" and row["lines"] == 0
    assert row["visas"] == {"stock": "none", "supply": "none", "engineer": "none"}
    assert {(a["zone"], a["name"]) for a in row["assignees"]} == {("goods", "Supply"), ("services", "Engineer")}

    mine = _api(world["accountant"]).get("/api/v1/calc/tasks/", {"mine": "1"})
    assert mine.json()["results"] == [], "бухгалтер не исполнитель резолюции"
    assert len(_api(world["engineer"]).get("/api/v1/calc/tasks/", {"mine": "1"}).json()["results"]) == 1


def test_client_side_user_gets_403(world):
    outsider = _user("buyer@client.test")
    assert _api(outsider).get("/api/v1/calc/tasks/").status_code == 403
    assert _api(outsider).get(_url(world)).status_code == 403


# ── начало расчёта и строки ─────────────────────────────────────────────────────────────────────────────────────────


def test_start_without_request_lines_makes_an_empty_draft_once(world):
    first = _api(world["supply"]).post(_url(world, "start/"))
    assert first.status_code == 200
    body = first.json()
    assert body["quote"]["state"] == "in_progress" and body["lines"] == []
    assert body["request"] == {"text": "Нужны 2 стрелочных перевода Р65 и монтаж бригадой", "lines": 0}
    assert body["ready"] == {"allowed": False, "blocker": "no_lines", "missing": 0}
    again = _api(world["engineer"]).post(_url(world, "start/"))
    assert again.status_code == 200
    assert Quote.objects.filter(deal=world["deal"]).count() == 1
    assert ActivityLog.objects.filter(deal=world["deal"], event_code="calc.started").count() == 1


def test_sheet_of_a_deal_without_calc_task_is_404(world):
    other = Deal.objects.create(title="Без резолюции", company=world["deal"].company)
    response = _api(world["supply"]).get(f"/api/v1/calc/{other.pk}/")
    assert response.status_code == 404 and response.json() == {"detail": "CALC_TASK_NOT_FOUND"}


def test_lines_get_kind_stock_supplier_and_zone(world):
    _started(world)
    body = _sheet(world, world["supply"])
    goods, service = body["lines"]
    assert goods["kind"] == "goods_to_order", "на складе 1, нужно 2"
    assert goods["stock"] == {"on_hand": 1, "cell": None, "reserved": None}
    assert goods["supplier"]["name"] == "ООО Вымышленный Поставщик"
    assert goods["supplier"]["lead_days"] == 45 and goods["supplier"]["price_valid_until"] == "2026-12-31"
    assert goods["article"] == "СП-Р65-11" and goods["group"] == "supply"
    assert service["kind"] == "service" and service["zone"] == "services" and service["group"] == "engineer"
    assert service["supplier"] is None
    assert body["visas"]["supply"]["state"] == "waiting" and body["visas"]["engineer"]["state"] == "waiting"
    assert body["visas"]["stock"]["state"] == "none"


def test_zone_matrix_for_adding_editing_and_signing(world):
    goods_id, service_id = _started(world)
    supply, engineer, accountant = (_api(world[k]) for k in ("supply", "engineer", "accountant"))

    # Снабженец не добавляет и не правит услуги, гл. инженер — товары.
    denied = supply.post(_url(world, "lines/"), {"lines": [{"name": "ПНР", "kind": "service"}]}, format="json")
    assert denied.status_code == 403 and denied.json()["detail"] == "ZONE_NOT_PERMITTED"
    assert supply.patch(_url(world, f"lines/{service_id}/"), {"crew_rate": "100"}, format="json").status_code == 403
    assert engineer.patch(_url(world, f"lines/{goods_id}/"), {"purchase_price": "1"}, format="json").status_code == 403
    assert supply.post(_url(world, f"lines/{service_id}/visa/")).status_code == 403
    assert engineer.post(_url(world, f"lines/{goods_id}/visa/")).status_code == 403
    # Без прав расчёта (бухгалтер) — 403 на любой мутации, чтение открыто.
    for method, path in (
        ("post", f"lines/{goods_id}/visa/"),
        ("patch", f"lines/{goods_id}/"),
        ("delete", f"lines/{goods_id}/"),
        ("post", "ready/"),
        ("post", "start/"),
    ):
        response = getattr(accountant, method)(_url(world, path), {"quantity": 3}, format="json")
        assert response.status_code == 403, (method, path)
    assert accountant.get(_url(world)).status_code == 200


def test_engineer_fills_crew_and_supply_fills_purchase_and_client_price(world):
    goods_id, service_id = _started(world)
    engineer, supply = _api(world["engineer"]), _api(world["supply"])

    response = engineer.patch(
        _url(world, f"lines/{service_id}/"), {"crew_rate": "1500000", "crew_days": "3"}, format="json"
    )
    assert response.status_code == 200, response.json()
    service = next(line for line in response.json()["lines"] if line["id"] == service_id)
    assert service["crew_rate"] == "1500000.00" and service["crew_days"] == "3.0"
    # Q-D2-1-2: себестоимость строк своей зоны гл. инженер видит, наценку и итоги — нет (нет cost_margin).
    assert service["cost"] == "4500000.00" and service["markup_pct"] is None
    assert response.json()["totals"]["purchase"] is None and response.json()["totals"]["markup_pct"] is None
    item = QuoteItem.objects.get(pk=service_id)
    assert item.frozen_base_price == Decimal("4500000.00") and item.landed_cost == Decimal("4500000.00")
    assert (
        supply.patch(_url(world, f"lines/{service_id}/"), {"purchase_price": "1"}, format="json").status_code == 403
    ), "закупку услуги правит только гл. инженер"
    response = engineer.patch(_url(world, f"lines/{service_id}/"), {"client_price": "5400000"}, format="json")
    assert response.status_code == 200, response.json()
    assert QuoteItem.objects.get(pk=service_id).margin_percent == Decimal("20.00")

    response = supply.patch(
        _url(world, f"lines/{goods_id}/"), {"purchase_price": "90000000", "client_price": "99000000"}, format="json"
    )
    assert response.status_code == 200, response.json()
    goods = next(line for line in response.json()["lines"] if line["id"] == goods_id)
    assert goods["cost"] == "90000000.00" and goods["client_price"] == "99000000.00" and goods["markup_pct"] == "10.0"
    totals = response.json()["totals"]
    assert totals["purchase"] == "189000000.00" and totals["client"] == "208800000.00"
    assert totals["vat_included"] is False

    below = supply.patch(_url(world, f"lines/{goods_id}/"), {"client_price": "1"}, format="json")
    assert below.status_code == 400 and below.json()["detail"] == "CLIENT_PRICE_BELOW_COST"


def _priced(world):
    goods_id, service_id = _started(world)
    _api(world["engineer"]).patch(
        _url(world, f"lines/{service_id}/"),
        {"crew_rate": "1500000", "crew_days": "3", "client_price": "5400000"},
        format="json",
    )
    _api(world["supply"]).patch(
        _url(world, f"lines/{goods_id}/"), {"purchase_price": "90000000", "client_price": "99000000"}, format="json"
    )
    return goods_id, service_id


def test_any_edit_withdraws_the_line_visa(world):
    goods_id, _service_id = _priced(world)
    supply = _api(world["supply"])
    signed = supply.post(_url(world, f"lines/{goods_id}/visa/"))
    assert signed.status_code == 200
    line = next(line for line in signed.json()["lines"] if line["id"] == goods_id)
    assert line["visa"]["by"] == "Supply"
    assert supply.post(_url(world, f"lines/{goods_id}/visa/")).status_code == 200, "повтор визы — без изменений"

    edited = supply.patch(_url(world, f"lines/{goods_id}/"), {"quantity": 3}, format="json")
    line = next(line for line in edited.json()["lines"] if line["id"] == goods_id)
    assert line["visa"] is None
    assert CalcLine.objects.get(item_id=goods_id).visa_at is None


def test_incomplete_line_cannot_be_signed(world):
    _api(world["supply"]).post(_url(world, "start/"))
    created = _api(world["supply"]).post(_url(world, "lines/"), {"lines": [{"name": "Болт М24"}]}, format="json")
    line_id = created.json()["created"][0]
    response = _api(world["supply"]).post(_url(world, f"lines/{line_id}/visa/"))
    assert response.status_code == 409 and response.json()["detail"] == "LINE_INCOMPLETE"


def test_ready_needs_every_visa_then_sends_the_quote_to_the_director(world):
    goods_id, service_id = _priced(world)
    supply, engineer = _api(world["supply"]), _api(world["engineer"])

    assert supply.post(_url(world, f"lines/{goods_id}/visa/")).status_code == 200
    early = supply.post(_url(world, "ready/"))
    assert early.status_code == 409 and early.json() == {"detail": "VISAS_MISSING", "missing": 1}
    assert bus_support.published("quote.ready_for_approval") == []
    sheet = _sheet(world, world["supply"])
    assert sheet["ready"] == {"allowed": False, "blocker": "visas_missing", "missing": 1}

    after = engineer.post(_url(world, f"lines/{service_id}/visa/"))
    assert after.json()["ready"] == {"allowed": True, "blocker": None, "missing": 0}
    done = engineer.post(_url(world, "ready/"))
    assert done.status_code == 200, done.json()
    assert done.json()["quote"]["state"] == "at_director"
    quote = Quote.objects.get(deal=world["deal"])
    assert quote.status.code == "PENDING_APPROVAL" and not quote.approval_steps.exists()
    event = bus_support.only("quote.ready_for_approval")
    bus_support.assert_matches_contract(event)
    payload = event["data"]["payload"]
    assert payload["required_zones"] == ["goods", "services"]
    assert sorted((v["zone"], v["by"]["crm_user_id"]) for v in payload["visas"]) == [("goods", 11), ("services", 12)]
    assert payload["min_margin_pct"] == "15.00"
    # КП у директора: строки больше не правятся.
    locked = supply.patch(_url(world, f"lines/{goods_id}/"), {"quantity": 5}, format="json")
    assert locked.status_code == 409 and locked.json()["detail"] == "QUOTE_NOT_DRAFT"
    row = _api(world["accountant"]).get("/api/v1/calc/tasks/").json()["results"][0]
    assert row["state"] == "at_director" and row["visas"] == {"stock": "none", "supply": "done", "engineer": "done"}


def test_delete_line_by_zone(world):
    goods_id, service_id = _started(world)
    assert _api(world["supply"]).delete(_url(world, f"lines/{service_id}/")).status_code == 403
    response = _api(world["engineer"]).delete(_url(world, f"lines/{service_id}/"))
    assert response.status_code == 200 and [line["id"] for line in response.json()["lines"]] == [goods_id]


def test_free_line_kind_decides_the_zone(world):
    _api(world["supply"]).post(_url(world, "start/"))
    response = _api(world["engineer"]).post(
        _url(world, "lines/"), {"lines": [{"name": "Пусконаладка", "kind": "service", "quantity": 1}]}, format="json"
    )
    assert response.status_code == 201
    (line,) = response.json()["lines"]
    assert line["zone"] == "services" and line["product_id"] is None and response.json()["created"] == [line["id"]]
    switch = _api(world["engineer"]).patch(_url(world, f"lines/{line['id']}/"), {"kind": "goods"}, format="json")
    assert switch.status_code == 403, "сделать строку товаром — зона снабженца"


def test_catalog_search_for_matching(world):
    response = _api(world["supply"]).get("/api/v1/calc/catalog/", {"q": "стрелочный Р65"})
    assert response.status_code == 200
    (row,) = response.json()["results"]
    assert row["id"] == world["rail"].pk and row["kind"] == "goods" and row["on_hand"] == 1
    assert row["supplier_name"] == "ООО Вымышленный Поставщик" and row["lead_days"] == 45
    assert _api(world["supply"]).get("/api/v1/calc/catalog/").json() == {"results": []}


def test_bind_free_line_to_catalog_card(world):
    _api(world["supply"]).post(_url(world, "start/"))
    created = _api(world["supply"]).post(
        _url(world, "lines/"), {"lines": [{"name": "перевод Р65", "quantity": 1}]}, format="json"
    )
    line_id = created.json()["created"][0]
    response = _api(world["supply"]).patch(
        _url(world, f"lines/{line_id}/"), {"product_id": world["rail"].pk}, format="json"
    )
    assert response.status_code == 200
    (line,) = response.json()["lines"]
    assert line["product_id"] == world["rail"].pk and line["kind"] == "goods" and line["stock"]["on_hand"] == 1


# ── ИИ-разбор: предложение без записи ───────────────────────────────────────────────────────────────────────────────


def test_parse_is_409_when_ai_is_off(world, settings):
    settings.AI_IMPORT_ENABLED = False
    response = _api(world["supply"]).post(_url(world, "parse/"), {}, format="json")
    assert response.status_code == 409 and response.json() == {"detail": "AI_DISABLED"}


def test_parse_queues_a_job_and_the_job_only_proposes(world, settings):
    from sourcing.tasks_ai import FEATURE_HANDLERS

    settings.AI_IMPORT_ENABLED = True
    with mock.patch("sourcing.ai_jobs.run_ai_job.apply_async") as queued:
        response = _api(world["supply"]).post(_url(world, "parse/"), {}, format="json")
    assert response.status_code == 202 and response.json()["task_id"]
    feature, payload = queued.call_args.kwargs["args"]
    assert feature == "calc_parse_text" and payload["text"].startswith("Нужны 2 стрелочных")

    rows = [{"name": "Перевод стрелочный Р65", "quantity": 2, "unit": "шт.", "mpn": "", "note": ""}]
    with mock.patch("ai.services.intake.extract_request_items", return_value=rows) as extract:
        result = FEATURE_HANDLERS["calc_parse_text"](payload)
    extract.assert_called_once()
    assert result["proposal"] == [
        {"name": "Перевод стрелочный Р65", "quantity": 2, "unit": "шт.", "article": "", "note": ""}
    ]
    assert not Quote.objects.filter(deal=world["deal"]).exists(), "предложение ничего не пишет"


def test_parse_without_text_is_409(world, settings):
    settings.AI_IMPORT_ENABLED = True
    Deal.objects.filter(pk=world["deal"].pk).update(notes="")
    response = _api(world["supply"]).post(_url(world, "parse/"), {}, format="json")
    assert response.status_code == 409 and response.json() == {"detail": "REQUEST_TEXT_EMPTY"}


# ── ответы совпадают с выгрузкой /api/v1 (страж D2-0: BFF читает ровно то, что обещает схема) ─────────────────────


def test_every_calc_operation_conforms_to_the_v1_schema(world, settings):
    from core.tests.openapi_fixtures import conforms, sends

    base = "/api/v1/calc/"
    deal = "{deal_id}/"
    supply, engineer = _api(world["supply"]), _api(world["engineer"])
    conforms(supply.get(f"{base}tasks/", {"scope": "all"}), f"{base}tasks/", "get", status=200)
    conforms(supply.get(_url(world)), f"{base}{deal}", "get", status=200)
    conforms(supply.post(_url(world, "start/")), f"{base}{deal}start/", "post", status=200)
    body = {"lines": [{"product_id": world["rail"].pk, "quantity": 2, "name": "", "kind": "goods"}]}
    sends(f"{base}{deal}lines/", "post", body)
    added = supply.post(_url(world, "lines/"), body, format="json")
    conforms(added, f"{base}{deal}lines/", "post", status=201)
    goods_id = added.json()["created"][0]
    patch = {"purchase_price": "90000000", "client_price": "99000000", "quantity": 2}
    sends(f"{base}{deal}lines/{{item_id}}/", "patch", patch)
    line = f"{base}{deal}lines/{{item_id}}/"
    conforms(supply.patch(_url(world, f"lines/{goods_id}/"), patch, format="json"), line, "patch", status=200)
    refused = engineer.patch(_url(world, f"lines/{goods_id}/"), {"quantity": 3}, format="json")
    conforms(refused, line, "patch", status=403)
    below = supply.patch(_url(world, f"lines/{goods_id}/"), {"client_price": "1"}, format="json")
    conforms(below, line, "patch", status=400)
    conforms(supply.post(_url(world, f"lines/{goods_id}/visa/")), f"{line}visa/", "post", status=200)
    conforms(supply.get(f"{base}catalog/", {"q": "Р65"}), f"{base}catalog/", "get", status=200)
    settings.AI_IMPORT_ENABLED = False
    conforms(supply.post(_url(world, "parse/"), {}, format="json"), f"{base}{deal}parse/", "post", status=409)
    conforms(supply.get(f"{base}999999/"), f"{base}{deal}", "get", status=404)
    # Единственная строка подтверждена — «Расчёт готов»; дальше строки не правятся (409).
    conforms(supply.post(_url(world, "ready/")), f"{base}{deal}ready/", "post", status=200)
    conforms(supply.delete(_url(world, f"lines/{goods_id}/")), line, "delete", status=409)
    conforms(supply.post(_url(world, "ready/")), f"{base}{deal}ready/", "post", status=409)


# ── доработки по ревью: ERP сам режет себестоимость, зона после правки, виза по версии, стадия ──────────────────


COST_KEYS = ("purchase_price", "cost", "markup_pct", "crew_rate", "crew_days")


def test_accountant_gets_no_cost_from_erp_directly(world):
    """Прямой вызов ERP /api/v1/calc/* бухгалтером: ни закупки, ни ставок бригады, ни цен поставщика, ни итогов
    себестоимости и наценки (решение по Q-D2-1-4) — режет сам ERP, не только BFF."""
    _priced(world)
    body = _sheet(world, world["accountant"])
    for line in body["lines"]:
        assert all(line[key] is None for key in COST_KEYS), line
        if line["supplier"]:
            assert line["supplier"]["offer_price"] is None and line["supplier"]["offer_currency"] is None
    assert body["totals"]["purchase"] is None and body["totals"]["markup_pct"] is None
    assert body["totals"]["client"] == "208800000.00"
    assert body["rights"] == {"goods": False, "services": False, "build": False, "cost": False}


def test_role_without_zone_gets_no_cost_even_in_write_responses(world):
    """Роль со строительством КП, но без зон и без себестоимости: чтение и ответ на «Начать расчёт» без себестоимости."""
    builder = _staff(world["seller"], "builder@demo.test", ["quote.build", "quote.edit_pricing", "deal.manage"])
    _priced(world)
    response = _api(builder).post(_url(world, "start/"))  # запись (повтор — без изменений) отдаёт расчёт
    assert response.status_code == 200
    for body in (response.json(), _sheet(world, builder)):
        for line in body["lines"]:
            assert all(line[key] is None for key in COST_KEYS), line
            if line["supplier"]:
                assert line["supplier"]["offer_price"] is None
        assert body["totals"]["purchase"] is None and body["totals"]["markup_pct"] is None
    assert (
        _api(builder)
        .patch(_url(world, f"lines/{response.json()['lines'][0]['id']}/"), {"quantity": 3}, format="json")
        .status_code
        == 403
    )


def test_zone_holders_see_cost_of_their_zone_only(world):
    _priced(world)
    engineer = _sheet(world, world["engineer"])
    goods, service = engineer["lines"]
    assert service["crew_rate"] == "1500000.00" and service["cost"] == "4500000.00"
    assert goods["purchase_price"] is None and goods["cost"] is None and goods["supplier"]["offer_price"] is None
    assert engineer["totals"]["purchase"] is None
    supply = _sheet(world, world["supply"])
    assert supply["lines"][0]["supplier"]["offer_price"] == "90000000.00"
    assert supply["totals"]["purchase"] == "189000000.00" and supply["totals"]["markup_pct"] is not None


def test_unbinding_a_service_card_keeps_the_service_zone(world):
    """Обход зоны через `product_id: null`: строка с карточкой услуги без карточки остаётся услугой."""
    _goods_id, service_id = _started(world)
    assert (
        _api(world["supply"])
        .patch(_url(world, f"lines/{service_id}/"), {"product_id": None}, format="json")
        .status_code
        == 403
    )
    response = _api(world["engineer"]).patch(_url(world, f"lines/{service_id}/"), {"product_id": None}, format="json")
    assert response.status_code == 200
    line = next(line for line in response.json()["lines"] if line["id"] == service_id)
    assert line["zone"] == "services" and line["product_id"] is None
    # Привязать к строке-услуге карточку товара гл. инженер не может: зона после правки — товары.
    rebind = _api(world["engineer"]).patch(
        _url(world, f"lines/{service_id}/"), {"product_id": world["rail"].pk}, format="json"
    )
    assert rebind.status_code == 403


def _visa_of(world, line_id):
    return next(line for line in _sheet(world, world["supply"])["lines"] if line["id"] == line_id)["visa"]


def test_visa_does_not_survive_an_edit_through_the_old_quote_item_paths(world):
    """Правка позиции старым API КП (`crm/quote-items`: PATCH, `reassign-product`) поднимает версию строки — виза
    расчёта, привязанная к версии, перестаёт действовать без ручного подъёма."""
    goods_id, _ = _priced(world)
    supply = _api(world["supply"])
    assert supply.post(_url(world, f"lines/{goods_id}/visa/")).status_code == 200
    assert _visa_of(world, goods_id) is not None

    patched = supply.patch(f"/api/v1/crm/quote-items/{goods_id}/", {"quantity": 5}, format="json")
    assert patched.status_code == 200, patched.json()
    assert _visa_of(world, goods_id) is None
    assert CalcLine.objects.get(item_id=goods_id).visa_at is not None, "факт визы в журнале строки остаётся"

    assert supply.post(_url(world, f"lines/{goods_id}/visa/")).status_code == 200
    assert _visa_of(world, goods_id) is not None
    rematched = supply.post(
        f"/api/v1/crm/quote-items/{goods_id}/reassign-product/", {"product_id": world["rail"].pk}, format="json"
    )
    assert rematched.status_code == 200, rematched.json()
    assert _visa_of(world, goods_id) is None


def test_ready_refuses_a_closed_deal(world):
    goods_id, service_id = _priced(world)
    _api(world["supply"]).post(_url(world, f"lines/{goods_id}/visa/"))
    _api(world["engineer"]).post(_url(world, f"lines/{service_id}/visa/"))
    Deal.objects.filter(pk=world["deal"].pk).update(stage=DealStage.objects.get(code="CLOSED_LOST"))
    response = _api(world["supply"]).post(_url(world, "ready/"))
    assert response.status_code == 409
    assert response.json() == {"detail": "DEAL_NOT_IN_CALCULATION", "stage": "CLOSED_LOST"}
    assert bus_support.published("quote.ready_for_approval") == []


def test_deal_refs_are_light_and_newest_first(world):
    from core.tests.openapi_fixtures import conforms

    other = Deal.objects.create(
        title="Вторая", company=world["deal"].company, stage=DealStage.objects.get(code="RFQ_OPEN")
    )
    calc_tasks.apply_resolution(
        other,
        eds_letter_id=uuid.UUID("0b1f5c0e-9a51-4c43-8a0e-3c1f0a2d5e02"),
        letter_number="ВХ-105/26",
        letter_subject="",
        text="Посчитать",
        due=date(2026, 11, 2),
        min_margin_pct=None,
        decided_by_crm_user_id=3,
        decided_by_name="Демо Директоров",
        decided_at=datetime(2026, 10, 27, 7, 0, tzinfo=timezone.utc),
        assignees=[calc_tasks.Assignment(11, "goods")],
    )
    response = _api(world["accountant"]).get("/api/v1/calc/deals/")
    conforms(response, "/api/v1/calc/deals/", "get", status=200)
    rows = response.json()["results"]
    assert [row["id"] for row in rows] == [other.pk, world["deal"].pk]
    assert set(rows[0]) == {"id", "number", "created_at", "stage_code"} and rows[0]["stage_code"] == "CALCULATING"
    assert rows[0]["number"] == other.number and other.number.startswith("ЗВ-")

    # отбор по номеру: префикс и ширина не важны (ПР — тот же NNN), не номер — пусто
    year, seq = other.number_year, other.number_seq
    for query in (other.number, f"zv {year} {seq}", f"ПР-{year}-{seq:03d}"):
        found = _api(world["accountant"]).get("/api/v1/calc/deals/", {"number": query}).json()["results"]
        assert [row["id"] for row in found] == [other.pk], query
    assert _api(world["accountant"]).get("/api/v1/calc/deals/", {"number": "ВХ-105/26"}).json() == {"results": []}


# ── повторное ревью: границы зон, порог маржи, стадия в готовности, act_on_step без виз строк ──────────────────


def test_goods_only_zone_holder_without_cost_margin_sees_no_service_cost(world):
    goods_only = _staff(world["seller"], "goods@demo.test", ["quote.build", "quote.edit_pricing", "quote.visa_goods"])
    _priced(world)
    body = _sheet(world, goods_only)
    goods, service = body["lines"]
    assert service["crew_rate"] is None and service["crew_days"] is None and service["cost"] is None
    assert service["purchase_currency"] is None
    assert goods["purchase_price"] == "90000000.00" and goods["supplier"]["offer_price"] == "90000000.00"
    assert goods["markup_pct"] is None and body["totals"]["purchase"] is None
    assert body["task"]["min_margin_pct"] is None, "порог маржи — только cost_margin"


def test_engineer_write_response_hides_goods_cost(world):
    goods_id, service_id = _priced(world)
    response = _api(world["engineer"]).patch(_url(world, f"lines/{service_id}/"), {"crew_days": "4"}, format="json")
    assert response.status_code == 200
    goods = next(line for line in response.json()["lines"] if line["id"] == goods_id)
    assert goods["purchase_price"] is None and goods["cost"] is None and goods["purchase_currency"] is None
    assert goods["supplier"]["offer_price"] is None and goods["supplier"]["offer_currency"] is None
    assert response.json()["task"]["min_margin_pct"] is None
    assert _sheet(world, world["supply"])["task"]["min_margin_pct"] == "15.00"


def test_sheet_says_why_ready_is_off_for_a_closed_deal(world):
    _priced(world)
    Deal.objects.filter(pk=world["deal"].pk).update(stage=DealStage.objects.get(code="CLOSED_LOST"))
    ready = _sheet(world, world["supply"])["ready"]
    assert ready["allowed"] is False and ready["blocker"] == "not_in_calculation"


def test_quote_level_visa_chain_does_not_mix_in_line_visas(world):
    """Отправка КП старым путём (визы КП шагами) — событие без подписей строк: они только у «Расчёт готов»."""
    from crm.services.eds_quote_approval import build_ready_payload

    goods_id, service_id = _priced(world)
    _api(world["supply"]).post(_url(world, f"lines/{goods_id}/visa/"))
    _api(world["engineer"]).post(_url(world, f"lines/{service_id}/visa/"))
    quote = Quote.objects.get(deal=world["deal"])
    now = datetime(2026, 10, 28, 9, 0, tzinfo=timezone.utc)
    plain = build_ready_payload(quote, ready_at=now)
    with_lines = build_ready_payload(quote, ready_at=now, line_visas=True)
    assert plain["required_zones"] == calc_tasks.required_visa_zones(calc_tasks.latest_task(world["deal"].pk))
    assert ("services", 12) not in [(v["zone"], v["by"]["crm_user_id"]) for v in plain["visas"]]
    assert sorted((v["zone"], v["by"]["crm_user_id"]) for v in with_lines["visas"]) == [("goods", 11), ("services", 12)]

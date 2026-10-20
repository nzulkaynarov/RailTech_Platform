"""Проекции integration на настоящие поля моделей (FIX-30, находки I-2, I-3, I-19; хвост FIX-12 — сумма).

Форму ответов целиком проверяет сторож `test_contract_integration.py`; здесь — смысл: какие сделки открыты, откуда
сумма и поставка, что видно CRM, что нет, и что `stage.code` читает одна функция.
"""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest
from integration.services.summary import (
    delivery_lines,
    get_company_summary_data,
    get_deal_detail_data,
    list_company_deals_data,
)
from integration.services.webhooks import build_deal_ref
from integration.tests.world import (
    TODAY,
    add_contract,
    add_fulfillment,
    add_invoice,
    add_order_quote,
    add_quote,
    build_integration_world,
    make_company,
    make_deal,
)
from rest_framework.test import APIClient
from rest_framework.throttling import SimpleRateThrottle
from sales.models import DeliveryLine, Fulfillment

from crm.constants import DealStageCode, FulfillmentStatusCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import Deal, FulfillmentStatus

pytestmark = pytest.mark.django_db

PREFIX = "/api/integration/v1"


@pytest.fixture(autouse=True)
def _env(settings, monkeypatch):
    settings.FRONTEND_URL = "http://erp.localhost"
    monkeypatch.setitem(SimpleRateThrottle.THROTTLE_RATES, "anon", "100000/minute")


@pytest.fixture
def client():
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION="Bearer test-service-token")
    return api


@pytest.fixture
def world():
    return build_integration_world()


def by_number(items, world_items):
    """{ключ мира: ответ} — по номеру записи, чтобы проверять статус каждой записи отдельно."""
    return {key: next((i for i in items if i["number"] == obj.number), None) for key, obj in world_items.items()}


# ── I-2: 500 на любой настоящей сделке со счётом или договором ─────────────────────────────────────


def test_deal_with_contract_and_invoice_answers_200(client):
    """Раньше `c.signed_at` и `inv.total_amount` не существовали, и ответ был 500 на любой настоящей сделке."""
    company = make_company()
    deal = make_deal(company, DealStageCode.CLOSED_WON)
    quote = add_quote(deal, 1, QuoteStatusCode.APPROVED, "5000000")
    contract = add_contract(deal, quote)
    add_invoice(deal, InvoiceStatusCode.PARTIAL, total="5000000", paid="1000000", contract=contract)

    for url in (f"/deals/{deal.pk}", f"/companies/{company.pk}/summary", f"/companies/{company.pk}/deals"):
        response = client.get(PREFIX + url)
        assert response.status_code == 200, f"{url}: {response.status_code}"

    body = client.get(f"{PREFIX}/deals/{deal.pk}").json()
    assert body["contracts"][0]["status"] == "signed"
    assert body["contracts"][0]["signed_at"] is not None
    assert body["invoices"][0]["total"] == {"amount": "5000000.00", "currency": "UZS"}
    assert body["invoices"][0]["paid"] == {"amount": "1000000.00", "currency": "UZS"}
    assert body["invoices"][0]["status"] == "partially_paid"


def test_money_uses_the_currency_of_the_document(client):
    from integration.tests.world import usd

    company = make_company()
    deal = make_deal(company, DealStageCode.CLOSED_WON)
    quote = add_quote(deal, 1, QuoteStatusCode.APPROVED, "1500", currency=usd())
    contract = add_contract(deal, quote)
    add_invoice(deal, total="1500", contract=contract, currency=usd())

    body = client.get(f"{PREFIX}/deals/{deal.pk}").json()
    assert body["currency"] == "USD"
    assert body["quotes"][0]["total"] == {"amount": "1500.00", "currency": "USD"}
    assert body["invoices"][0]["total"]["currency"] == "USD"


# ── Статусы документов: те же функции, что у Cabinet ──────────────────────────────────────────────────


def test_document_statuses_come_from_the_portal_projections(client, world):
    body = client.get(f"{PREFIX}/deals/{world['full'].pk}").json()

    contracts = by_number(body["contracts"], world["contracts"])
    assert {key: item["status"] if item else None for key, item in contracts.items()} == {
        "sent": "sent",
        "signed_by_client": "signed_by_client",
        "signed_by_company": "signed_by_company",
        "signed": "signed",
        "cancelled": None,  # клиент (и CRM) не видят аннулированный и черновой договор
        "draft": None,
    }
    assert contracts["signed"]["signed_at"] is not None
    assert all(contracts[key]["signed_at"] is None for key in ("sent", "signed_by_client", "signed_by_company"))

    invoices = by_number(body["invoices"], world["invoices"])
    assert {key: item["status"] if item else None for key, item in invoices.items()} == {
        "issued": "issued",
        "partially_paid": "partially_paid",
        "paid": "paid",
        "overdue": "overdue",
        "cancelled": "cancelled",
        "draft": None,
    }
    assert invoices["partially_paid"]["paid"]["amount"] == "1000000.00"

    acts = by_number(body["acts"], world["acts"])
    assert {key: item["status"] if item else None for key, item in acts.items()} == {
        "issued": "issued",
        "accepted": "accepted",
        "returned": "returned",
        "cancelled": None,
        "draft": None,
    }


def test_overdue_invoice_with_past_due_date_is_overdue_even_if_status_not_set(client):
    deal = make_deal(make_company(), DealStageCode.CLOSED_WON)
    add_invoice(deal, InvoiceStatusCode.ISSUED, due=TODAY - datetime.timedelta(days=5))
    assert client.get(f"{PREFIX}/deals/{deal.pk}").json()["invoices"][0]["status"] == "overdue"


def test_draft_quotes_are_visible_to_crm_but_not_in_client_view(world):
    detail = get_deal_detail_data(world["full"].pk)
    client_detail = get_deal_detail_data(world["full"].pk, client_view=True)
    statuses = {q["version"]: q["status"] for q in detail["quotes"]}
    assert statuses[7] == "draft" and statuses[8] == "approval"
    assert {q["version"] for q in client_detail["quotes"]} == {1, 2, 3, 4, 5, 6}
    sent_url = next(q for q in detail["quotes"] if q["version"] == 1)["public_url"]
    assert sent_url == f"http://erp.localhost/api/v1/public/quotes/{world['sent_quote'].public_access_token}/"
    assert next(q for q in detail["quotes"] if q["version"] == 7)["public_url"] is None


# ── Сумма сделки: без черновиков, везде одинаково ─────────────────────────────────────────────────────


def test_amount_is_the_same_in_answers_and_event_deal_ref(client, world):
    full = world["full"]
    assert full.quotes.filter(version__in=(7, 8)).count() == 2  # более новые версии есть, но это черновики
    expected = "84000000.00"

    deal = client.get(f"{PREFIX}/deals/{full.pk}").json()
    listed = next(
        d for d in client.get(f"{PREFIX}/companies/{world['company'].pk}/deals").json() if d["erp_deal_id"] == full.pk
    )
    summary = get_company_summary_data(world["company"].pk)
    ref = build_deal_ref(Deal.objects.get(pk=full.pk))

    assert deal["amount"] == listed["amount"] == ref["amount"] == expected
    assert ref["stage"] == deal["stage"] == listed["stage"]
    assert all(d["amount"] == expected for d in summary["open_deals"] if d["erp_deal_id"] == full.pk)


def test_amount_is_null_until_the_client_gets_a_quote(client):
    company = make_company()
    deal = make_deal(company, DealStageCode.CALCULATING)
    add_quote(deal, 1, QuoteStatusCode.DRAFT, "5000000")
    add_quote(deal, 2, QuoteStatusCode.READY_TO_SEND, "6000000")

    body = client.get(f"{PREFIX}/deals/{deal.pk}").json()
    assert body["amount"] is None
    assert client.get(f"{PREFIX}/companies/{company.pk}/deals").json()[0]["amount"] is None
    assert get_company_summary_data(company.pk)["open_deals"][0]["amount"] is None
    assert build_deal_ref(Deal.objects.get(pk=deal.pk))["amount"] is None


# ── Открытые сделки: закрытые по стадии контракта, а не по коду FSM ───────────────────────────────────


def test_closed_deals_are_not_open_but_unfinished_won_deals_are():
    """I-3: `exclude(stage__code__in=['won','lost'])` не совпадал ни с одним кодом, и закрытые попадали в открытые."""
    company = make_company()
    from integration.tests.world import build_lost, build_won

    lost = build_lost(company)
    won = build_won(company)
    signed_only = make_deal(company, DealStageCode.CLOSED_WON, "Договор подписан, оплаты нет")
    add_contract(signed_only, add_quote(signed_only, 1, QuoteStatusCode.APPROVED, "1000000"))

    summary = get_company_summary_data(company.pk)
    open_ids = {d["erp_deal_id"] for d in summary["open_deals"]}
    assert open_ids == {signed_only.pk}
    all_stages = {d["erp_deal_id"]: d["stage"] for d in list_company_deals_data(company.pk)}
    assert all_stages[lost.pk] == "lost" and all_stages[won.pk] == "won" and all_stages[signed_only.pk] == "contract"


# ── Дебиторка и ближайшая поставка ────────────────────────────────────────────────────────────────────


def test_receivables_count_only_unpaid_balances_of_issued_invoices(world):
    # Сделка «всё сразу»: issued 84 000 000 + partially_paid (84 000 000 − 1 000 000) + overdue 84 000 000 = 251 000 000;
    # оплаченный, аннулированный и черновик не в счёт. Плюс 5 000 000 неоплаченного счёта у сделки стадии `invoiced`.
    summary = get_company_summary_data(world["company"].pk)
    assert summary["receivables"] == {"amount": "256000000.00", "currency": "UZS"}


def test_partial_invoice_is_receivable():
    """Раньше искали `PARTIALLY_PAID` при коде `PARTIAL`, и частично оплаченный счёт в дебиторку не попадал."""
    company = make_company()
    deal = make_deal(company, DealStageCode.CLOSED_WON)
    add_invoice(deal, InvoiceStatusCode.PARTIAL, total="3000000", paid="1000000")
    assert get_company_summary_data(company.pk)["receivables"] == {"amount": "2000000.00", "currency": "UZS"}


def test_next_delivery_is_the_nearest_pending_line_from_delivery_lines(world):
    nearest = get_company_summary_data(world["company"].pk)["next_delivery"]
    assert nearest is not None
    assert nearest["status"] in {"assembling", "in_transit", "shipped", "ready_to_ship"}
    assert nearest["eta"] is not None
    assert DeliveryLine.objects.filter(deal_id=nearest["erp_deal_id"], line_no=nearest["line_no"]).exists()
    # доставленное и принятое клиентом не «ближайшее»
    assert nearest["status"] not in {"delivered", "accepted", "disputed"}


def test_next_delivery_prefers_the_earliest_eta_and_skips_delivered():
    company = make_company()
    soon, later, done = datetime.timedelta(days=2), datetime.timedelta(days=9), datetime.timedelta(days=1)
    deals = {}
    for key, code, eta in (
        ("later", FulfillmentStatusCode.SHIPPED, TODAY + later),
        ("soon", FulfillmentStatusCode.IN_TRANSIT, TODAY + soon),
        ("done", FulfillmentStatusCode.DELIVERED, TODAY + done),
    ):
        deal = make_deal(company, DealStageCode.CONTRACT_SIGNED, key)
        add_order_quote(deal)
        add_fulfillment(deal, code, expected_delivery_date=eta, tracking_number=f"TRK-{key}")
        deals[key] = deal
    nearest = get_company_summary_data(company.pk)["next_delivery"]
    assert nearest["erp_deal_id"] == deals["soon"].pk
    assert nearest["tracking"] == "TRK-soon"

    Fulfillment.objects.filter(deal=deals["soon"]).update(status=FulfillmentStatus.objects.get(code="DELIVERED"))
    Fulfillment.objects.filter(deal=deals["later"]).update(status=FulfillmentStatus.objects.get(code="DELIVERED"))
    assert get_company_summary_data(company.pk)["next_delivery"] is None


def test_deliveries_follow_the_warehouse_without_the_client_opening_the_cabinet(client):
    """Строки поставки доводятся до хода исполнения при чтении: статус не зависит от того, заходил ли клиент в Cabinet."""
    deal = make_deal(make_company(), DealStageCode.CONTRACT_SIGNED)
    add_order_quote(deal)
    fulfillment = add_fulfillment(deal, FulfillmentStatusCode.PENDING)
    assert {d["status"] for d in client.get(f"{PREFIX}/deals/{deal.pk}").json()["deliveries"]} == {"assembling"}

    Fulfillment.objects.filter(pk=fulfillment.pk).update(
        status=FulfillmentStatus.objects.get(code="SHIPPED"), tracking_number="TRK-77"
    )
    deliveries = client.get(f"{PREFIX}/deals/{deal.pk}").json()["deliveries"]
    assert {d["status"] for d in deliveries} == {"shipped"} and {d["tracking"] for d in deliveries} == {"TRK-77"}


def test_client_decision_on_a_line_survives_the_sync_and_is_reported(client, world):
    deliveries = client.get(f"{PREFIX}/deals/{world['deliveries']['disputed'].deal_id}").json()["deliveries"]
    assert {d["status"] for d in deliveries} == {"disputed"}
    assert {d["remark"] for d in deliveries} == {"Не хватает двух штук"}
    accepted = client.get(f"{PREFIX}/deals/{world['deliveries']['accepted'].deal_id}").json()["deliveries"]
    assert {d["status"] for d in accepted} == {"accepted"} and all(d["accepted_at"] for d in accepted)


def test_delivery_line_without_quantity_is_null_not_invented():
    deal = make_deal(make_company(), DealStageCode.CONTRACT_SIGNED)
    add_order_quote(deal)
    add_fulfillment(deal, FulfillmentStatusCode.SHIPPED)
    delivery_lines(deal)
    DeliveryLine.objects.filter(deal=deal).update(quantity=None, unit="", tracking="")
    for line in delivery_lines(deal):
        assert line["quantity"] is None and line["unit"] is None and line["tracking"] is None


def test_fulfillment_without_order_quote_has_no_lines():
    """Заказа нет — строк нет, и название сделки за строку поставки не выдаётся."""
    deal = make_deal(make_company(), DealStageCode.CONTRACT_SIGNED)
    add_fulfillment(deal, FulfillmentStatusCode.SHIPPED)
    assert delivery_lines(deal) == []
    assert DeliveryLine.objects.filter(deal=deal).count() == 0


# ── Каталог: только поля контракта (I-19) ─────────────────────────────────────────────────────────────


def test_catalog_service_returns_only_contract_fields():
    from integration.services.catalog import search_published_catalog

    from catalog.models import Category, Product, ProductStatus
    from core.models import Currency
    from master_data.models import UnitOfMeasure

    uzs, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум"})
    unit, _ = UnitOfMeasure.objects.get_or_create(code="796", defaults={"name": "шт"})
    published, _ = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликован"})
    Product.objects.create(
        name="Рельс Р65 каталог",
        category=Category.objects.create(name="Рельсы"),
        uom=unit,
        status=published,
        list_price=1,
        list_price_currency=uzs,
        price_visibility="cabinet",
    )
    for mode, allowed in (
        ("lead", {"erp_product_id", "kind", "name", "description", "unit"}),
        (
            "client",
            {"erp_product_id", "kind", "name", "description", "unit", "price", "availability", "lead_time_days"},
        ),
    ):
        (item,) = search_published_catalog("Рельс Р65 каталог", mode)
        assert set(item) <= allowed, f"{mode}: лишнее {set(item) - allowed}"


# ── Одна функция стадий ───────────────────────────────────────────────────────────────────────────────

INTEGRATION = Path(__file__).resolve().parents[1]
#: Файлы вне `stages.py`, где пока читается код стадии FSM. Запись убирает та задача, что переводит файл на `stages.py`.
STAGE_CODE_ALLOWLIST: dict[str, str] = {}
STAGE_CODE_MARKERS = ("stage.code", "stage__code")


def _sources_reading_stage_code():
    found = {}
    for path in sorted(INTEGRATION.rglob("*.py")):
        relative = path.relative_to(INTEGRATION).as_posix()
        if relative.startswith(("tests/", "migrations/")) or relative == "services/stages.py":
            continue
        text = path.read_text(encoding="utf-8")
        marks = [m for m in STAGE_CODE_MARKERS if m in text]
        if marks:
            found[relative] = marks
    return found


def test_only_stages_py_reads_the_fsm_stage_code():
    """`deal.stage.code` в ответ или событие — это сырой код FSM вместо `DealStage` контракта (I-3). Читает его `stages.py`."""
    offenders = set(_sources_reading_stage_code()) - set(STAGE_CODE_ALLOWLIST)
    assert not offenders, f"код стадии FSM читается мимо integration/services/stages.py: {sorted(offenders)}"


def test_stage_code_allowlist_has_no_stale_entries():
    stale = set(STAGE_CODE_ALLOWLIST) - set(_sources_reading_stage_code())
    assert not stale, f"файл больше не читает код стадии — убери из STAGE_CODE_ALLOWLIST: {sorted(stale)}"


def test_summary_does_not_swallow_errors():
    """Раньше `next_delivery` всегда был `null` из-за `except Exception: pass` — ошибка проекции не должна глотаться."""
    assert "except Exception" not in (INTEGRATION / "services" / "summary.py").read_text(encoding="utf-8")


def test_webhooks_has_no_second_stage_mapping():
    from integration.services import webhooks

    assert not hasattr(webhooks, "map_deal_stage") and not hasattr(webhooks, "VALID_DEAL_STAGES")

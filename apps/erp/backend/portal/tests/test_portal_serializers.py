"""Форма каждого сериализатора портала (FIX-21): значения полей и схема контракта 0.2.0.

Сторож (`test_contract_guard.py`) проверяет ответы эндпоинтов целиком; здесь — по сериализатору: что именно
кладётся в каждое поле, откуда оно берётся и что внутренние поля не просачиваются. Каждый ответ дополнительно
сверяется со схемой компонента из `erp-portal.yaml` (типы, форматы, `required`, лишние ключи).
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest
from portal.models import PortalRequestLine
from portal.projections import annotate_request_sources, delivery_lines
from portal.serializers import (
    ActSerializer,
    ClientRequestSerializer,
    CompanySerializer,
    ContractSerializer,
    DealRefSerializer,
    DeliveryLineSerializer,
    InvoiceSerializer,
    MeSerializer,
    PortalDocumentSerializer,
    QuoteListItemSerializer,
    QuoteSerializer,
    TeamMemberSerializer,
)
from portal.tests.contract_support import check_response, component
from portal.tests.contract_world import make_quote
from rest_framework.renderers import JSONRenderer

from crm.constants import ContractStatusCode, FulfillmentStatusCode, QuoteStatusCode
from crm.models import Act, ActivityLog, Deal, Fulfillment, FulfillmentStatus, Invoice, Quote, QuoteItem, QuoteStatus

pytestmark = pytest.mark.django_db


def wire(data):
    """Данные сериализатора так, как их увидит клиент: через JSON-рендерер."""
    return json.loads(JSONRenderer().render(data))


def assert_matches_contract(data, schema_name):
    problems = check_response(wire(data), component(schema_name))
    assert not problems, f"{schema_name}: " + "; ".join(problems)


def fresh_deal(pk):
    return (
        Deal.objects.filter(pk=pk)
        .select_related("stage", "portal_summary")
        .prefetch_related("quotes__status", "portal_lines", "portal_uploads")
        .get()
    )


# ── DealRef ───────────────────────────────────────────────────────────────────────────────────────


def test_deal_ref_has_id_number_title(contract_world):
    deal = contract_world["main"]
    data = DealRefSerializer(deal).data
    assert data == {"id": deal.pk, "number": f"D-{deal.pk}", "title": "Поставка труб"}
    assert_matches_contract(data, "DealRef")


def test_deal_ref_title_is_null_when_blank(contract_world):
    data = DealRefSerializer(contract_world["in_progress"]).data
    assert data["title"] is None
    assert_matches_contract(data, "DealRef")


# ── ClientRequest ──────────────────────────────────────────────────────────────────────────────────


def test_new_request_has_no_deal_yet_and_carries_lines_and_attachments(contract_world):
    deal = fresh_deal(contract_world["new_deal"].pk)
    annotate_request_sources([deal])
    data = ClientRequestSerializer(deal).data
    assert data["number"] == f"Z-{deal.pk}"
    assert data["status"] == "new"
    assert data["deal"] is None and data["deal_id"] is None
    assert data["source"] == "cabinet"
    assert data["lines"] == [
        {"text": "Труба 89х4", "quantity": "150", "unit": "м"},
        {"text": "Что-нибудь без количества", "quantity": None, "unit": None},  # количество не выдумывается
    ]
    assert data["attachments"] == [{"upload_id": str(deal.portal_uploads.get().upload_id), "name": "specification.pdf"}]
    assert_matches_contract(data, "ClientRequest")


@pytest.mark.parametrize(
    ("key", "status", "source"),
    [("in_progress", "in_progress", "erp"), ("closed", "closed", "crm"), ("main", "quoted", "crm")],
)
def test_request_after_work_started_refers_to_its_deal(contract_world, key, status, source):
    deal = fresh_deal(contract_world[key].pk)
    data = ClientRequestSerializer(deal).data
    assert data["status"] == status
    assert data["deal"] == {"id": deal.pk, "number": f"D-{deal.pk}", "title": deal.title or None}
    assert data["deal_id"] == deal.pk
    assert data["source"] == source  # по журналу создания: сотрудник ERP → erp, нет записи (передача из CRM) → crm
    assert_matches_contract(data, "ClientRequest")


def test_request_summary_is_the_full_client_text_or_the_deal_title(contract_world):
    from portal.models import PortalRequestSummary

    deal = contract_world["in_progress"]
    assert (
        ClientRequestSerializer(fresh_deal(deal.pk)).data["summary"] == f"Запрос #{deal.pk}"
    )  # ни названия, ни текста
    deal = contract_world["main"]
    assert ClientRequestSerializer(fresh_deal(deal.pk)).data["summary"] == "Поставка труб"
    PortalRequestSummary.objects.create(deal=deal, text="я" * 5000)
    assert ClientRequestSerializer(fresh_deal(deal.pk)).data["summary"] == "я" * 5000


def test_request_source_is_taken_from_the_creation_journal(contract_world):
    deal = contract_world["main"]
    ActivityLog.objects.create(deal=deal, action="Создан", event_code="deal.created", event_params={"source": "crm"})
    assert ClientRequestSerializer(fresh_deal(deal.pk)).data["source"] == "crm"


def test_request_list_does_not_query_per_deal(contract_world, django_assert_max_num_queries):
    deals = list(
        Deal.objects.filter(company=contract_world["company"])
        .select_related("stage", "portal_summary")
        .prefetch_related("quotes__status", "portal_lines", "portal_uploads")
    )
    with django_assert_max_num_queries(1):  # только журнал источника; остальное — из prefetch
        annotate_request_sources(deals)
        ClientRequestSerializer(deals, many=True).data


# ── Quote ──────────────────────────────────────────────────────────────────────────────────────────


def test_quote_list_item_fields(contract_world):
    quote = contract_world["quotes"]["sent"]
    data = QuoteListItemSerializer(quote).data
    assert set(data) == {"id", "deal", "deal_id", "number", "version", "status", "total", "valid_until", "sent_at"}
    assert data["deal"]["number"] == f"D-{quote.deal_id}"
    assert data["total"] == {"amount": str(quote.total_incl_vat), "currency": "UZS"}
    assert_matches_contract(data, "QuoteListItem")


def test_quote_sent_at_is_the_send_date_not_updated_at(contract_world):
    quote = contract_world["quotes"]["sent"]
    frozen = quote.frozen_at
    Quote.objects.filter(pk=quote.pk).update(updated_at=frozen + datetime.timedelta(days=30))
    quote.refresh_from_db()
    sent_at = QuoteListItemSerializer(quote).data["sent_at"]
    assert datetime.datetime.fromisoformat(sent_at) == frozen
    assert datetime.datetime.fromisoformat(sent_at) != quote.updated_at


def test_quote_detail_lines_keep_sections_and_notes_and_skip_optional(contract_world):
    quote = contract_world["quotes"]["viewed"]
    data = QuoteSerializer(quote).data
    assert [line["kind"] for line in data["lines"]] == ["section", "item", "item", "note"]
    assert [line["line_no"] for line in data["lines"]] == [1, 2, 3, 4]
    assert data["lines"][0]["title"] == "Трубы"
    assert data["lines"][0]["unit_price"] is None and data["lines"][0]["total"] is None
    assert data["lines"][3]["title"] == "Цены действительны 14 дней"
    assert all("Опциональный монтаж" != line["title"] for line in data["lines"])
    first = data["lines"][1]
    assert first["title"] == "Труба 89х4 ст20" and first["quantity"] == "150" and first["unit"] == "м"
    assert first["unit_price"]["currency"] == "UZS" and first["total"]["currency"] == "UZS"
    assert first["promised_date"] is None  # срок обещания клиенту не выдумывается
    assert_matches_contract(data, "Quote")


def test_quote_detail_has_no_internal_fields(contract_world):
    data = QuoteSerializer(contract_world["quotes"]["sent"]).data
    for internal in ("vat_rate", "items", "payment_terms", "delivery_basis", "lead_time_days", "updated_at"):
        assert internal not in data
    for line in data["lines"]:
        for internal in ("id", "name", "price", "total_price", "vat_amount", "cost", "margin"):
            assert internal not in line


def test_quote_charges_are_spread_into_line_prices_not_listed_separately(contract_world):
    """У `sent` в фикстуре `charges_total` 50000: сумма строк = подитог + статьи, отдельной строки расходов нет."""
    quote = Quote.objects.get(pk=contract_world["quotes"]["sent"].pk)
    data = QuoteSerializer(quote).data
    totals = [Decimal(line["total"]["amount"]) for line in data["lines"] if line["kind"] == "item"]
    assert sum(totals) == quote.subtotal_excl_vat + quote.charges_total
    assert len([line for line in data["lines"] if line["kind"] == "item"]) == 2


def test_quote_public_url_is_the_public_page_link(contract_world):
    from crm.services.documents.public_page import public_quote_url

    quote = contract_world["quotes"]["sent"]
    assert QuoteSerializer(quote).data["public_url"] == public_quote_url(quote)
    assert quote.public_access_token in QuoteSerializer(quote).data["public_url"]


def test_quote_rejected_reason_only_for_rejected(contract_world):
    quotes = contract_world["quotes"]
    assert QuoteSerializer(quotes["rejected"]).data["rejected_reason"] == "Дорого"
    assert QuoteSerializer(quotes["sent"]).data["rejected_reason"] is None
    assert_matches_contract(QuoteSerializer(quotes["rejected"]).data, "Quote")


def test_quote_without_recorded_reason_has_null_reason(contract_world):
    ActivityLog.objects.filter(event_code="quote.rejected").delete()
    assert QuoteSerializer(contract_world["quotes"]["rejected"]).data["rejected_reason"] is None


def test_quote_pdf_document_is_its_entry_in_documents(contract_world):
    sent = QuoteSerializer(contract_world["quotes"]["sent"]).data
    assert sent["pdf_document_id"] == contract_world["documents"]["quote_sent"]
    draft = Quote.objects.get(deal=contract_world["internal_deal"], version=1)
    assert QuoteSerializer(draft).data["pdf_document_id"] is None  # КП не отправлено — документа нет


def test_quote_items_of_a_catalog_product_use_its_name_and_unit(contract_world):
    deal = contract_world["other"]["deal"]
    quote = make_quote(deal, 2, QuoteStatusCode.SENT, uzs=contract_world["uzs"], items=False)
    QuoteItem.objects.create(
        quote=quote, product=contract_world["product"], imported_raw_name="труба клиента", quantity=2, unit=""
    )
    line = QuoteSerializer(quote).data["lines"][0]
    assert line["title"] == "Труба 89х4 ст20"  # как в PDF: карточка каталога главнее строки клиента
    assert line["unit"] == "шт"  # единица из карточки, когда в строке её нет


# ── Contract ───────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("sent", "sent"),
        ("signed_by_client", "signed_by_client"),
        ("signed_by_company", "signed_by_company"),
        ("signed", "signed"),
        ("cancelled", "cancelled"),
        ("draft", "sent"),  # черновик клиенту не должен показываться — правило FIX-22; форма остаётся валидной
    ],
)
def test_contract_status_mapping(contract_world, key, expected):
    data = ContractSerializer(contract_world["contracts"][key]).data
    assert data["status"] == expected
    assert_matches_contract(data, "Contract")


def test_contract_fields_and_signature_dates(contract_world):
    contract = contract_world["contracts"]["signed"]
    data = ContractSerializer(contract).data
    assert set(data) == {
        "id",
        "deal",
        "deal_id",
        "number",
        "status",
        "signed_by_client_at",
        "signed_by_company_at",
        "document_id",
    }
    assert data["signed_by_client_at"] is not None and data["signed_by_company_at"] is not None
    pending = ContractSerializer(contract_world["contracts"]["sent"]).data
    assert pending["signed_by_client_at"] is None and pending["signed_by_company_at"] is None


def test_contract_document_id_is_its_entry_in_documents_not_the_contract_id(contract_world):
    contract = contract_world["contracts"]["signed"]
    document_id = ContractSerializer(contract).data["document_id"]
    assert document_id == contract_world["documents"]["contract_signed"] and document_id != contract.pk
    assert ContractSerializer(contract_world["contracts"]["draft"]).data["document_id"] is None


def test_contract_status_codes_are_all_mapped():
    """Каждый статус ERP отображается в статус контракта (новый статус ERP не должен выпасть из enum)."""
    contract_enum = set(component("ContractStatus")["enum"])
    from portal.projections import contract_status

    class Fake:
        manager_signed_at = None

        def __init__(self, code, manager=None):
            self.status = type("S", (), {"code": code})()
            self.manager_signed_at = manager

    for code in ContractStatusCode.values:
        assert contract_status(Fake(code)) in contract_enum
    assert contract_status(Fake(ContractStatusCode.PENDING_CLIENT, manager=object())) == "signed_by_company"


# ── Invoice ────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("issued", "issued"),
        ("partially_paid", "partially_paid"),
        ("paid", "paid"),
        ("overdue", "overdue"),
        ("cancelled", "cancelled"),
    ],
)
def test_invoice_status_mapping_and_form(contract_world, key, expected):
    invoice = contract_world["invoices"][key]
    data = InvoiceSerializer(invoice).data
    assert data["status"] == expected
    assert set(data) == {"id", "deal", "deal_id", "number", "status", "total", "paid", "due_date", "document_id"}
    assert "paid_amount" not in data
    assert data["paid"]["currency"] == "UZS"
    assert_matches_contract(data, "Invoice")


def test_invoice_paid_is_the_amount_paid(contract_world):
    data = InvoiceSerializer(contract_world["invoices"]["partially_paid"]).data
    assert data["paid"] == {"amount": "1000000.00", "currency": "UZS"}
    assert data["total"] == {"amount": "84000000.00", "currency": "UZS"}


def test_overdue_is_computed_from_due_date(contract_world):
    invoice = contract_world["invoices"]["issued"]
    Invoice.objects.filter(pk=invoice.pk).update(due_date=datetime.date.today() - datetime.timedelta(days=1))
    invoice.refresh_from_db()
    assert InvoiceSerializer(invoice).data["status"] == "overdue"


# ── Act ────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("key", "expected"),
    [("issued", "issued"), ("accepted", "accepted"), ("returned", "returned"), ("cancelled", "issued")],
)
def test_act_status_mapping_and_form(contract_world, key, expected):
    act = contract_world["acts"][key]
    data = ActSerializer(act).data
    assert data["status"] == expected
    assert set(data) == {
        "id",
        "deal",
        "deal_id",
        "number",
        "status",
        "issued_at",
        "returned_reason",
        "document_id",
        "scan_document_id",
    }
    assert "signed_at" not in data and "return_reason" not in data and "total" not in data
    assert_matches_contract(data, "Act")


def test_act_returned_reason_only_when_returned(contract_world):
    assert ActSerializer(contract_world["acts"]["returned"]).data["returned_reason"] == "Не совпадает количество"
    assert ActSerializer(contract_world["acts"]["issued"]).data["returned_reason"] is None


def test_act_returned_by_the_old_portal_code_path_is_still_returned(contract_world):
    """Прежний возврат писал статус NULL и причину: такая запись остаётся `returned` (чинит FIX-22)."""
    act = contract_world["acts"]["returned"]
    Act.objects.filter(pk=act.pk).update(status=None)
    act.refresh_from_db()
    assert ActSerializer(act).data["status"] == "returned"


def test_act_scan_is_null_until_the_lifecycle_task_exposes_it(contract_world):
    act = contract_world["acts"]["accepted"]
    assert act.signed_file
    assert ActSerializer(act).data["scan_document_id"] is None


# ── DeliveryLine ───────────────────────────────────────────────────────────────────────────────────


def _lines(world, key):
    fulfillment = Fulfillment.objects.select_related("status", "deal").get(pk=world["deliveries"][key].pk)
    return delivery_lines([fulfillment])


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("assembling", "assembling"),
        ("shipped", "shipped"),
        ("in_transit", "in_transit"),
        ("delivered", "delivered"),
        ("accepted", "accepted"),
        ("disputed", "disputed"),
    ],
)
def test_delivery_status_mapping(contract_world, key, expected):
    lines = _lines(contract_world, key)
    assert lines and {line["status"] for line in lines} == {expected}
    for line in DeliveryLineSerializer(lines, many=True).data:
        assert_matches_contract(line, "DeliveryLine")


def test_delivery_lines_are_the_billable_items_of_the_confirmed_quote(contract_world):
    lines = _lines(contract_world, "in_transit")
    assert [line["line_no"] for line in lines] == [1, 2]
    assert [line["title"] for line in lines] == [
        "Труба 89х4 ст20",
        "Отвод 89х4",
    ]  # без раздела, заметки и опционального
    approved = Quote.objects.get(deal=lines[0]["deal"], status__code=QuoteStatusCode.APPROVED)
    item_ids = list(approved.items.billable().order_by("position").values_list("id", flat=True))
    assert [line["id"] for line in lines] == item_ids
    assert lines[0]["quantity"] == "150" and lines[0]["unit"] == "м"
    assert lines[0]["tracking"] == "TRK-0001"
    assert lines[0]["eta"] is not None and lines[0]["shipped_at"] is not None


def test_delivery_line_does_not_invent_missing_data(contract_world):
    lines = _lines(contract_world, "assembling")
    assert lines[0]["tracking"] is None and lines[0]["eta"] is None
    assert lines[0]["shipped_at"] is None and lines[0]["accepted_at"] is None
    assert lines[0]["remark"] is None
    QuoteItem.objects.filter(pk=lines[0]["id"]).update(unit="")
    assert _lines(contract_world, "assembling")[0]["unit"] is None  # нет единицы в КП и карточке — null, не «компл.»


def test_delivery_line_has_no_fulfillment_when_there_is_no_confirmed_quote(contract_world):
    bare = Fulfillment.objects.select_related("status", "deal").get(deal__title="Без КП")
    assert delivery_lines([bare]) == []


def test_delivery_takes_the_latest_confirmed_quote_version(contract_world):
    deal = contract_world["deliveries"]["delivered"].deal
    newer = Quote.objects.create(
        deal=deal,
        version=2,
        status=QuoteStatus.objects.get(code=QuoteStatusCode.APPROVED),
        quote_currency=contract_world["uzs"],
    )
    QuoteItem.objects.create(quote=newer, imported_raw_name="Новая редакция", quantity=1, unit="шт")
    fulfillment = Fulfillment.objects.select_related("status", "deal").get(
        pk=contract_world["deliveries"]["delivered"].pk
    )
    assert [line["title"] for line in delivery_lines([fulfillment])] == ["Новая редакция"]


def test_delivery_line_has_no_price_or_supplier(contract_world):
    for line in DeliveryLineSerializer(_lines(contract_world, "shipped"), many=True).data:
        assert not {"price", "unit_price", "total", "supplier", "cost"} & set(line)


# ── Document ───────────────────────────────────────────────────────────────────────────────────────


def _portal_document(world, key):
    from django.utils import translation
    from portal.services.documents import find_client_document

    with translation.override("ru"):
        return find_client_document(world["company"], world["documents"][key])


@pytest.mark.parametrize(
    ("key", "kind"),
    [
        ("quote_sent", "quote"),
        ("contract_signed", "contract"),
        ("invoice_paid", "invoice"),
        ("act_accepted", "act"),
        ("waybill_shipped", "waybill"),
        ("generated_contract", "contract"),
    ],
)
def test_document_kind_and_form(contract_world, key, kind):
    document = _portal_document(contract_world, key)
    data = PortalDocumentSerializer(document).data
    assert data["kind"] == kind
    assert set(data) == {"id", "deal", "deal_id", "kind", "number", "date", "title", "file_name", "size_bytes"}
    assert data["deal"]["id"] == document.deal_id and data["deal_id"] == document.deal_id
    assert data["file_name"].endswith(".pdf") and data["size_bytes"] > 0
    assert_matches_contract(data, "Document")


def test_document_without_deal_has_null_deal(contract_world):
    data = PortalDocumentSerializer(_portal_document(contract_world, "generated_no_deal")).data
    assert data["deal"] is None and data["deal_id"] is None and data["size_bytes"] == 0
    assert_matches_contract(data, "Document")


# ── Me / TeamMember / Company ───────────────────────────────────────────────────────────────────


def test_team_member_blank_email_and_phone_are_null(client_contact):
    client_contact.email = ""
    client_contact.phone = ""
    data = TeamMemberSerializer(client_contact).data
    assert data["email"] is None and data["phone"] is None
    assert_matches_contract(data, "TeamMember")


def test_team_member_form(client_contact):
    data = TeamMemberSerializer(client_contact).data
    assert set(data) == set(component("TeamMember")["properties"])
    assert data["has_telegram"] is True and data["preferred_channel"] == "both"


def test_company_form(client_company):
    data = CompanySerializer(client_company).data
    assert set(data) == set(component("Company")["properties"])
    assert_matches_contract(data, "Company")


def test_me_form(client_contact, client_company):
    data = MeSerializer(
        {
            "contact": TeamMemberSerializer(client_contact).data,
            "company": CompanySerializer(client_company).data,
            "can_act": True,
            "auth_method": "telegram",
        }
    ).data
    assert set(data) == set(component("Me")["properties"])
    assert_matches_contract(data, "Me")


def test_portal_request_line_without_quantity_is_not_a_fabricated_one(contract_world):
    """Строка без количества в базе отдаётся с `quantity: null`, а не «1»."""
    PortalRequestLine.objects.create(deal=contract_world["main"], text="Без количества", quantity=None, unit="")
    data = ClientRequestSerializer(fresh_deal(contract_world["main"].pk)).data
    assert data["lines"][-1] == {"text": "Без количества", "quantity": None, "unit": None}


def test_fulfillment_status_codes_are_all_mapped():
    from portal.projections import delivery_status

    enum = set(component("DeliveryStatus")["enum"])

    class Fake:
        def __init__(self, code):
            self.status = type("S", (), {"code": code})()

    for code in FulfillmentStatusCode.values:
        assert delivery_status(Fake(code)) in enum
    assert FulfillmentStatus.objects.count() >= 0  # справочник сеется миграциями

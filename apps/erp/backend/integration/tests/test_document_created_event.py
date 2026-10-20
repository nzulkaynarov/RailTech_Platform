"""Событие `document.created` (FIX-38): шлётся, когда документ выпущен клиенту, и несёт id документа портала.

Правило «выпущен» одно с порталом (`portal.services.documents.is_issued`): черновик, КП до отправки, отменённый и
внутренний документ события не дают; событие — на переходе в «выпущен», а не на каждом сохранении. Тело проверяется по
`packages/contracts/events.schema.json`.
"""

from __future__ import annotations

import pytest
from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus
from integration.models import IntegrationWebhookEvent
from integration.tests.world import (
    add_act,
    add_contract,
    add_fulfillment,
    add_invoice,
    add_order_quote,
    add_quote,
    make_company,
    make_deal,
)
from portal.services.documents import SLOT_BY_SOURCE, encode_document_id

from core.tests.events_contract import event_errors
from crm.constants import ActStatusCode, ContractStatusCode, FulfillmentStatusCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _env(settings):
    settings.ERP_WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture
def company():
    return make_company(crm_client_id=7001)


@pytest.fixture
def deal(company):
    return make_deal(company)


def created(kind: str | None = None) -> list[dict]:
    """Тела событий `document.created` в порядке выпуска (каждое проверено по схеме событий); `kind` — только этого вида."""
    envelopes = [
        e.payload for e in IntegrationWebhookEvent.objects.filter(event_type="document.created").order_by("id")
    ]
    for envelope in envelopes:
        assert not event_errors(envelope), event_errors(envelope)
    return [e for e in envelopes if kind in (None, e["payload"]["kind"])]


def generated(company, deal, *, kind="CONTRACT", status="ISSUED", contact=None):
    kind_row, _ = DocumentTemplateKind.objects.get_or_create(code=kind, defaults={"name": kind})
    template, _ = DocumentTemplate.objects.get_or_create(
        company=company, name=f"Шаблон {kind}", defaults={"kind": kind_row}
    )
    status_row, _ = GeneratedDocumentStatus.objects.get_or_create(code=status, defaults={"name": status})
    count = GeneratedDocument.objects.count()
    return GeneratedDocument.objects.create(
        company=company,
        deal=deal,
        contact=contact,
        template=template,
        status=status_row,
        number=f"DOC-EV-{count}",
        title=f"Док {count}",
    )


def set_status(model, status_model, record, code):
    """Смена статуса через `save()`, как в ERP: сигнал `post_save` видит переход."""
    record.status = status_model.objects.get_or_create(code=code, defaults={"name": code})[0]
    record.save()
    return record


# ── GeneratedDocument ───────────────────────────────────────────────────────────────────────────────


def test_issued_generated_document_event_has_the_portal_id(company, deal):
    document = generated(company, deal, kind="INVOICE")
    [event] = created()
    payload = event["payload"]
    assert payload["erp_document_id"] == encode_document_id("generated", document.pk) != document.pk
    assert (payload["kind"], payload["number"], payload["title"]) == ("invoice", document.number, document.title)
    assert event["deal"]["erp_deal_id"] == deal.pk


def test_draft_generated_document_gives_no_event_until_it_is_issued(company, deal):
    document = generated(company, deal, status="DRAFT")
    assert created() == []
    set_status(GeneratedDocument, GeneratedDocumentStatus, document, "ISSUED")
    [event] = created()
    assert event["payload"]["erp_document_id"] == encode_document_id("generated", document.pk)


def test_resaving_an_issued_document_does_not_repeat_the_event(company, deal):
    document = generated(company, deal)
    document.title = "Новое название"
    document.save()
    document.save()
    assert len(created()) == 1


@pytest.mark.parametrize(
    "kind,status",
    [("CONTRACT", "DRAFT"), ("INVOICE", "CANCELLED"), ("LETTER", "ISSUED"), ("REPORT", "ISSUED"), ("CUSTOM", "ISSUED")],
)
def test_draft_cancelled_and_internal_generated_documents_give_no_event(company, deal, kind, status):
    generated(company, deal, kind=kind, status=status)
    assert created() == []


def test_generated_document_without_deal_is_announced_through_its_contact(company):
    from parties.models import Contact

    generated(company, None, kind="ACT")
    assert created() == [], "документ без сделки и контакта клиенту не принадлежит"
    contact = Contact.objects.filter(company=company).first()
    document = generated(company, None, kind="ACT", contact=contact)
    [event] = created()
    assert event["payload"]["erp_document_id"] == encode_document_id("generated", document.pk)


def test_company_without_crm_mapping_gets_no_event():
    stranger = make_company("ООО Без CRM", crm_client_id=None)
    generated(stranger, make_deal(stranger))
    assert created() == []


# ── КП, договор, счёт, акт, накладная ───────────────────────────────────────────────────────────────


def test_quote_event_comes_when_it_is_sent_not_as_a_draft(deal):
    draft = add_quote(deal, 1, QuoteStatusCode.DRAFT, "1000000")
    assert created() == []
    sent = add_quote(deal, 2, QuoteStatusCode.SENT, "1000000")
    [event] = created()
    assert event["payload"]["erp_document_id"] == encode_document_id("quote", sent.pk)
    assert event["payload"]["kind"] == "quote"
    # черновик отправили: переход «не выпущен → выпущен» даёт событие, повторное сохранение — нет
    draft.public_access_token = "tok-ev-1"
    set_status(Quote, QuoteStatus, draft, QuoteStatusCode.SENT)
    assert [e["payload"]["erp_document_id"] for e in created()][-1] == encode_document_id("quote", draft.pk)
    draft.save()
    assert len(created()) == 2


def test_quote_decision_after_sending_is_not_a_new_document(deal):
    quote = add_quote(deal, 1, QuoteStatusCode.SENT, "1000000")
    set_status(Quote, QuoteStatus, quote, QuoteStatusCode.APPROVED)
    assert len(created()) == 1


def test_contract_event_comes_when_it_goes_to_the_client(deal):
    accepted = add_order_quote(deal)
    contract = add_contract(deal, accepted, ContractStatusCode.DRAFT)
    assert created("contract") == []
    set_status(Contract, ContractStatus, contract, ContractStatusCode.PENDING_CLIENT)
    [event] = created("contract")
    assert event["payload"]["erp_document_id"] == encode_document_id("contract", contract.pk)
    set_status(Contract, ContractStatus, contract, ContractStatusCode.SIGNED)
    assert len(created("contract")) == 1, "подпись — не новый документ"
    add_contract(deal, accepted, ContractStatusCode.CANCELLED)
    assert len(created("contract")) == 1, "аннулированный договор клиенту не выпускался"


def test_invoice_event_comes_when_it_is_issued_not_as_a_draft(deal):
    invoice = add_invoice(deal, InvoiceStatusCode.DRAFT, "1000", "0")
    assert created("invoice") == []
    set_status(Invoice, InvoiceStatus, invoice, InvoiceStatusCode.ISSUED)
    [event] = created("invoice")
    assert event["payload"]["erp_document_id"] == encode_document_id("invoice", invoice.pk)
    assert event["payload"]["kind"] == "invoice"
    set_status(Invoice, InvoiceStatus, invoice, InvoiceStatusCode.PAID)
    assert len(created("invoice")) == 1


def test_act_event_comes_when_it_is_issued_not_as_a_draft_or_cancelled(deal):
    act = add_act(deal, ActStatusCode.DRAFT)
    add_act(deal, ActStatusCode.CANCELLED)
    assert created("act") == []
    set_status(Act, ActStatus, act, ActStatusCode.ISSUED)
    [event] = created("act")
    assert event["payload"]["erp_document_id"] == encode_document_id("act", act.pk)
    assert event["payload"]["kind"] == "act"
    set_status(Act, ActStatus, act, ActStatusCode.SIGNED)
    assert len(created("act")) == 1


def test_waybill_event_comes_with_the_shipment(deal):
    add_order_quote(deal)
    fulfillment = add_fulfillment(deal, FulfillmentStatusCode.PENDING)
    assert created("waybill") == []
    set_status(Fulfillment, FulfillmentStatus, fulfillment, FulfillmentStatusCode.SHIPPED)
    [event] = created("waybill")
    assert event["payload"]["erp_document_id"] == encode_document_id("waybill", fulfillment.pk)
    assert event["payload"]["kind"] == "waybill"
    set_status(Fulfillment, FulfillmentStatus, fulfillment, FulfillmentStatusCode.DELIVERED)
    assert len(created("waybill")) == 1


def test_event_ids_have_the_portal_slot_of_their_source(deal):
    accepted = add_order_quote(deal)
    contract = add_contract(deal, accepted, ContractStatusCode.PENDING_CLIENT)
    invoice = add_invoice(deal, InvoiceStatusCode.ISSUED, "1000", "0")
    act = add_act(deal, ActStatusCode.ISSUED)
    ids = {e["payload"]["kind"]: e["payload"]["erp_document_id"] for e in created()}
    assert ids["contract"] % 8 == SLOT_BY_SOURCE["contract"] and ids["contract"] // 8 == contract.pk
    assert ids["invoice"] % 8 == SLOT_BY_SOURCE["invoice"] and ids["invoice"] // 8 == invoice.pk
    assert ids["act"] % 8 == SLOT_BY_SOURCE["act"] and ids["act"] // 8 == act.pk
    assert ids["quote"] % 8 == SLOT_BY_SOURCE["quote"] and ids["quote"] // 8 == accepted.pk

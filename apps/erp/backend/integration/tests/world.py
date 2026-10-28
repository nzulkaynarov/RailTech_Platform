"""Построители данных для тестов integration (FIX-30): сделки, КП, договоры, счета, акты и исполнение в нужных статусах.

Только настоящие коды справочников ERP (`crm/constants.py`): тесты, заводящие несуществующие стадии, были причиной
того, что `GET /deals/{id}` отвечал 500 на любой настоящей сделке и никто этого не видел (I-2, I-3).
"""

from __future__ import annotations

import datetime
import itertools
import uuid
from decimal import Decimal

from django.utils import timezone
from integration.models import CrmClientMapping
from parties.models import Company, Contact
from portal.tests.contract_world import make_quote

from core.models import Currency
from crm.constants import (
    ActStatusCode,
    ContractStatusCode,
    DealStageCode,
    FulfillmentStatusCode,
    InvoiceStatusCode,
    QuoteStatusCode,
)
from crm.models import (
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Payment,
    Quote,
    QuoteStatus,
)

TODAY = datetime.date.today()
_counter = itertools.count(1)


def lookup(model, code):
    """Строка справочника с настоящим кодом (в тестовой БД её сеют миграции)."""
    obj, _ = model.objects.get_or_create(code=code, defaults={"name": code})
    return obj


def uzs() -> Currency:
    return Currency.objects.get_or_create(code="UZS", defaults={"name": "Узбекский сум", "symbol": "so'm"})[0]


def usd() -> Currency:
    return Currency.objects.get_or_create(code="USD", defaults={"name": "Доллар США", "symbol": "$"})[0]


def make_company(name="ООО Клиент", crm_client_id=7001, inn=None) -> Company:
    company = Company.objects.create(name=name, inn=inn or f"{next(_counter):09d}")
    if crm_client_id is not None:
        CrmClientMapping.objects.create(crm_client_id=crm_client_id, company=company)
    Contact.objects.create(
        company=company, name="Иван", email=f"i{company.pk}@client.uz", is_primary=True, can_act=True
    )
    return company


def make_deal(company, fsm_code=DealStageCode.DRAFT, title="Поставка рельсов") -> Deal:
    return Deal.objects.create(company=company, stage=lookup(DealStage, fsm_code), title=title)


def add_quote(deal, version, status_code, total, *, currency=None, sent=None, valid_until=None, viewed=False) -> Quote:
    """КП с заданной суммой с НДС (без позиций). `sent` — выдать номер и публичную ссылку (по умолчанию — для отправленных)."""
    sent = (
        status_code in (QuoteStatusCode.SENT, QuoteStatusCode.APPROVED, QuoteStatusCode.REJECTED)
        if sent is None
        else sent
    )
    quote = Quote.objects.create(
        deal=deal,
        version=version,
        status=lookup(QuoteStatus, status_code),
        quote_currency=currency or uzs(),
        total_incl_vat=Decimal(total),
        valid_until=valid_until,
    )
    if sent:
        quote.number = f"Q-{deal.pk}-{version}-{next(_counter)}"
        quote.public_access_token = uuid.uuid4().hex
        quote.frozen_at = timezone.now() - datetime.timedelta(days=2)
        if viewed:
            quote.first_viewed_at = timezone.now() - datetime.timedelta(days=1)
        quote.save()
    return quote


def sign_via_scan(contract_id, actor=None):
    """Договор «Подписан» тем единственным путём, что остался после D2-5: «Выставлен у оператора» → скан (подпись кликом закрыта)."""
    from django.core.files.uploadedfile import SimpleUploadedFile

    from crm.services import contract_flow

    for action, extra in (
        ("mark_issued", {}),
        ("attach_scan", {"scan": SimpleUploadedFile("scan.pdf", b"%PDF-1.4 demo scan", "application/pdf")}),
    ):
        contract, error = contract_flow.apply_transition(contract_id, action, actor, **extra)
        assert error is None, f"{action}: {error}"
    return contract


def add_contract(deal, quote, status_code=ContractStatusCode.SIGNED, **fields) -> Contract:
    if status_code == ContractStatusCode.SIGNED:
        fields.setdefault("client_signed_at", timezone.now())
        fields.setdefault("manager_signed_at", timezone.now())
    return Contract.objects.create(
        deal=deal,
        quote=quote,
        number=f"CT-{next(_counter)}",
        status=lookup(ContractStatus, status_code),
        total_amount=quote.total_incl_vat,
        currency=quote.quote_currency,
        **fields,
    )


def add_invoice(
    deal, status_code=InvoiceStatusCode.ISSUED, total="1000000", paid="0", *, contract=None, due=None, **fields
):
    invoice = Invoice.objects.create(
        deal=deal,
        contract=contract,
        number=f"INV-{next(_counter)}",
        status=lookup(InvoiceStatus, status_code),
        issued_at=fields.pop("issued_at", TODAY),
        due_date=due or TODAY + datetime.timedelta(days=14),
        total_incl_vat=Decimal(total),
        amount_paid=Decimal(paid),
        currency=fields.pop("currency", None) or uzs(),
        **fields,
    )
    if Decimal(paid) > 0:
        Payment.objects.create(invoice=invoice, amount=Decimal(paid), paid_at=TODAY, reference=f"PAY-{invoice.pk}")
    return invoice


def add_act(deal, status_code=ActStatusCode.ISSUED, *, contract=None, invoice=None, **fields) -> Act:
    if status_code == ActStatusCode.SIGNED:
        fields.setdefault("signed_at", timezone.now())
        fields.setdefault("acceptor_signed_at", timezone.now())
    return Act.objects.create(
        deal=deal,
        contract=contract,
        invoice=invoice,
        number=f"ACT-{next(_counter)}",
        status=lookup(ActStatus, status_code),
        issued_at=TODAY,
        total_amount=Decimal("1000000"),
        **fields,
    )


def add_fulfillment(deal, status_code=FulfillmentStatusCode.PENDING, **fields) -> Fulfillment:
    return Fulfillment.objects.create(deal=deal, status=lookup(FulfillmentStatus, status_code), **fields)


def add_order_quote(deal, version=1, *, currency=None) -> Quote:
    """Подтверждённое КП с позициями — из него `sync_delivery_lines` строит строки поставки."""
    return make_quote(deal, version, QuoteStatusCode.APPROVED, uzs=currency or uzs())


# ── По одной сделке на каждую стадию контракта (`DealStage`) ──────────────────────────────────────────
# Единый набор для тестов стадий и сторожа контракта: сделка собирается из настоящих документов, а не из «кода стадии».


def build_request(company):
    return make_deal(company, DealStageCode.RFQ_OPEN)


def build_quoting(company):
    deal = make_deal(company, DealStageCode.CALCULATING)
    add_quote(deal, 1, QuoteStatusCode.DRAFT, "5000000")
    return deal


def build_quote_sent(company):
    deal = make_deal(company, DealStageCode.QUOTE_SENT)
    add_quote(deal, 1, QuoteStatusCode.SENT, "5000000")
    return deal


def build_accepted(company):
    """КП акцептовано (FSM `CONTRACT_SIGNED`), договор клиенту ещё не выставлен."""
    deal = make_deal(company, DealStageCode.CONTRACT_SIGNED)
    add_quote(deal, 1, QuoteStatusCode.APPROVED, "5000000")
    return deal


def build_signed_contract_deal(company):
    """Договор подписан обеими сторонами → FSM `CLOSED_WON`, но до счёта, оплаты и поставки далеко."""
    deal = make_deal(company, DealStageCode.CLOSED_WON)
    quote = add_quote(deal, 1, QuoteStatusCode.APPROVED, "5000000")
    contract = add_contract(deal, quote, ContractStatusCode.SIGNED)
    return deal, contract


def build_contract(company):
    deal = make_deal(company, DealStageCode.CONTRACT_SIGNED)
    quote = add_quote(deal, 1, QuoteStatusCode.APPROVED, "5000000")
    add_contract(deal, quote, ContractStatusCode.PENDING_CLIENT)
    return deal


def build_invoiced(company):
    deal, contract = build_signed_contract_deal(company)
    add_invoice(deal, InvoiceStatusCode.ISSUED, total="5000000", contract=contract)
    return deal


def build_paid(company):
    deal, contract = build_signed_contract_deal(company)
    add_invoice(deal, InvoiceStatusCode.PAID, total="5000000", paid="5000000", contract=contract)
    add_fulfillment(deal, FulfillmentStatusCode.PENDING)  # исполнение заводится сразу при подписании договора
    return deal


def build_fulfilment(company):
    deal, contract = build_signed_contract_deal(company)
    add_invoice(deal, InvoiceStatusCode.PAID, total="5000000", paid="5000000", contract=contract)
    add_fulfillment(deal, FulfillmentStatusCode.SHIPPED)
    return deal


def build_closing(company):
    deal, contract = build_signed_contract_deal(company)
    invoice = add_invoice(deal, InvoiceStatusCode.PAID, total="5000000", paid="5000000", contract=contract)
    add_fulfillment(deal, FulfillmentStatusCode.DELIVERED)
    add_act(deal, ActStatusCode.ISSUED, contract=contract, invoice=invoice)
    return deal


def build_won(company):
    deal, contract = build_signed_contract_deal(company)
    invoice = add_invoice(deal, InvoiceStatusCode.PAID, total="5000000", paid="5000000", contract=contract)
    add_fulfillment(deal, FulfillmentStatusCode.ACCEPTED)
    add_act(deal, ActStatusCode.SIGNED, contract=contract, invoice=invoice)
    return deal


def build_lost(company):
    return make_deal(company, DealStageCode.CLOSED_LOST)


STAGE_CASES = [
    ("request", build_request),
    ("quoting", build_quoting),
    ("quote_sent", build_quote_sent),
    ("accepted", build_accepted),
    ("contract", build_contract),
    ("invoiced", build_invoiced),
    ("paid", build_paid),
    ("fulfilment", build_fulfilment),
    ("closing", build_closing),
    ("won", build_won),
    ("lost", build_lost),
]


# ── Мир сторожа контракта: сделки со всем, что умеет отдавать integration ─────────────────────────────


def _make_document(company, deal):
    from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus

    kind, _ = DocumentTemplateKind.objects.get_or_create(code="CONTRACT", defaults={"name": "Договор"})
    template, _ = DocumentTemplate.objects.get_or_create(
        company=company, name="Договор поставки", defaults={"kind": kind}
    )
    status, _ = GeneratedDocumentStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Выпущен"})
    return GeneratedDocument.objects.create(
        company=company, deal=deal, template=template, status=status, number="CTR-GUARD-1", title="Договор поставки"
    )


def build_integration_world() -> dict:
    """Клиент А (с сопоставлением CRM) со всем набором статусов, пустой клиент Б и сделки на каждую стадию.

    * `full` — сделка «КП, договор, счёт, оплата, строки поставки, акт» во всех статусах, которые integration умеет отдать;
    * `empty` — пустая сделка без единого документа;
    * `deliveries` — по сделке на статус исполнения (строки поставки строятся из подтверждённого заказа);
    * `stages` — по сделке на каждую из 11 стадий контракта.
    """
    from sales.models import DeliveryLine

    company = make_company("ООО Клиент А", crm_client_id=7001)
    world: dict = {"company": company, "empty_company": make_company("ООО Пустой", crm_client_id=7002)}
    past = TODAY - datetime.timedelta(days=3)
    future = TODAY + datetime.timedelta(days=10)
    now = timezone.now()

    # ── Сделка «всё сразу» ────────────────────────────────────────────────────────────────────────
    full = make_deal(company, DealStageCode.CLOSED_WON, "Поставка труб")
    sent = add_quote(full, 1, QuoteStatusCode.SENT, "10000000", valid_until=future)
    add_quote(full, 2, QuoteStatusCode.SENT, "10000000", valid_until=future, viewed=True)
    add_quote(full, 3, QuoteStatusCode.SENT, "10000000", valid_until=past)  # истёк срок
    add_quote(full, 4, QuoteStatusCode.REJECTED, "9000000")
    add_quote(full, 5, "EXPIRED", "9000000", sent=True, valid_until=past)
    accepted = add_order_quote(full, version=6)  # APPROVED с позициями: из них строятся строки поставки
    Quote.objects.filter(pk=accepted.pk).update(total_incl_vat=Decimal("84000000.00"))
    accepted.refresh_from_db()
    # Последние версии — не для клиента: на сумму сделки и в клиентскую выдачу не влияют
    add_quote(full, 7, QuoteStatusCode.DRAFT, "99000000")
    add_quote(full, 8, QuoteStatusCode.PENDING_APPROVAL, "98000000")
    world.update(full=full, sent_quote=sent, accepted_quote=accepted)

    contracts = {}
    for key, status_code, extra in (
        ("sent", ContractStatusCode.PENDING_CLIENT, {}),
        ("signed_by_client", ContractStatusCode.PENDING_MANAGER, {"client_signed_at": now}),
        ("signed_by_company", ContractStatusCode.PENDING_CLIENT, {"manager_signed_at": now}),
        ("signed", ContractStatusCode.SIGNED, {}),
        ("cancelled", ContractStatusCode.CANCELLED, {}),
        ("draft", ContractStatusCode.DRAFT, {}),
    ):
        contracts[key] = add_contract(full, accepted, status_code, **extra)
    world["contracts"] = contracts

    invoices = {}
    for key, status_code, due, paid in (
        ("issued", InvoiceStatusCode.ISSUED, future, "0"),
        ("partially_paid", InvoiceStatusCode.PARTIAL, future, "1000000"),
        ("paid", InvoiceStatusCode.PAID, past, "84000000"),
        ("overdue", InvoiceStatusCode.OVERDUE, past, "0"),
        ("cancelled", InvoiceStatusCode.CANCELLED, future, "0"),
        ("draft", InvoiceStatusCode.DRAFT, future, "0"),
    ):
        invoices[key] = add_invoice(full, status_code, "84000000", paid, contract=contracts["signed"], due=due)
    world["invoices"] = invoices

    acts = {}
    for key, status_code, extra in (
        ("issued", ActStatusCode.ISSUED, {}),
        ("accepted", ActStatusCode.SIGNED, {}),
        ("returned", ActStatusCode.DRAFT, {"rejection_reason": "Не совпадает количество"}),
        ("cancelled", ActStatusCode.CANCELLED, {}),
        ("draft", ActStatusCode.DRAFT, {}),
    ):
        acts[key] = add_act(full, status_code, contract=contracts["signed"], invoice=invoices["paid"], **extra)
    world["acts"] = acts

    world["fulfillment"] = add_fulfillment(
        full,
        FulfillmentStatusCode.IN_TRANSIT,
        shipped_at=now,
        tracking_number="TRK-0001",
        expected_delivery_date=future,
    )
    world["document"] = _make_document(company, full)

    # ── Пустая сделка ─────────────────────────────────────────────────────────────────────────────
    world["empty"] = make_deal(company, DealStageCode.DRAFT, "")

    # ── Поставки во всех статусах строки ──────────────────────────────────────────────────────────
    deliveries = {}
    for key, code in (
        ("assembling", FulfillmentStatusCode.PENDING),
        ("shipped", FulfillmentStatusCode.SHIPPED),
        ("in_transit", FulfillmentStatusCode.IN_TRANSIT),
        ("delivered", FulfillmentStatusCode.DELIVERED),
        ("accepted", FulfillmentStatusCode.ACCEPTED),
        ("disputed", FulfillmentStatusCode.DISPUTED),
    ):
        deal = make_deal(company, DealStageCode.CONTRACT_SIGNED, f"Поставка {key}")
        add_order_quote(deal)
        extra = {}
        if key != "assembling":
            extra.update(shipped_at=now, tracking_number="TRK-0002", expected_delivery_date=future)
        if key in ("delivered", "accepted"):
            extra.update(delivered_at=now)
        if key == "accepted":
            extra.update(accepted_at=now)
        deliveries[key] = add_fulfillment(deal, code, **extra)
    world["deliveries"] = deliveries
    # Замечание клиента при `disputed` — поле `remark` строки; приёмка и спор ставит клиент через портал (FIX-22)
    from sales.services.delivery_lines import sync_delivery_lines

    sync_delivery_lines(deliveries.values())
    DeliveryLine.objects.filter(deal=deliveries["disputed"].deal).update(remark="Не хватает двух штук")

    # ── По сделке на каждую стадию контракта ───────────────────────────────────────────────────────
    world["stages"] = {expected: build(company) for expected, build in STAGE_CASES}
    return world

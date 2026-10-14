"""D2 — «регистр + печатный артефакт» (spec-d2-payments-shipments-registry-2026-08-01).

Платёж и отгрузка остаются записями регистра; в документооборот попадает их печатный
артефакт — квитанция об оплате (Odoo Payment Receipt) и накладная (Odoo Delivery Slip).
Self-contained lookups: тесты бегут с --nomigrations.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import (
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    DocumentTemplateKind,
    Fulfillment,
    FulfillmentStatus,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)
from crm.services.billing import generate_invoice_from_contract, record_payment
from crm.services.document_blocks import company_template_for, render_delivery_note_body, render_receipt_body
from crm.services.invoice_lifecycle import issue_invoice
from notifications.models import NotificationType


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    for code in ("CLIENT", "SUPPLIER"):
        CompanyType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    for code in ("DRAFT", "CONTRACT_SIGNED", "CLOSED_WON"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    for code in ("DRAFT", "SIGNED", "CANCELLED"):
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("PENDING", "IN_TRANSIT", "DELIVERED"):
        FulfillmentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 10})
    for code, name in (("RECEIPT", "Квитанция"), ("DELIVERY_NOTE", "Накладная")):
        DocumentTemplateKind.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})


@pytest.fixture
def world(lookups):
    buyer_co = Company.objects.create(
        name="Buyer R",
        inn="B907",
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    seller_co = Company.objects.create(
        name="Seller R",
        inn="S907",
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller_user = CustomUser.objects.create_user(email="s@reg.test", username="s@reg.test", password="x")
    CompanyMember.objects.create(
        user=seller_user,
        company=seller_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    buyer_user = CustomUser.objects.create_user(email="b@reg.test", username="b@reg.test", password="x")
    CompanyMember.objects.create(
        user=buyer_user,
        company=buyer_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_buy=True,
    )
    deal = Deal.objects.create(title="R deal", company=buyer_co, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=seller_user,
        seller_company=seller_co,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-REG-907",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    return {
        "seller_co": seller_co,
        "seller_user": seller_user,
        "buyer_user": buyer_user,
        "deal": deal,
        "contract": contract,
    }


def _paid_invoice(world):
    invoice, err = generate_invoice_from_contract(world["contract"].id, actor=None)
    assert err is None
    invoice, err = issue_invoice(invoice, world["seller_user"])
    assert err is None
    payment, err = record_payment(invoice.id, world["buyer_user"], amount=Decimal("112"), paid_at=timezone.localdate())
    assert err is None, err
    invoice.refresh_from_db()
    return invoice, payment


@pytest.mark.django_db
def test_platform_samples_exist_for_receipt_and_delivery_note():
    """Rule 1: заготовки приходят миграцией."""
    for kind in ("RECEIPT", "DELIVERY_NOTE"):
        sample = company_template_for(None, kind)
        assert sample is not None, kind
        assert sample.is_sample and sample.company_id is None


@pytest.mark.django_db
def test_payment_gets_a_receipt_number_and_body_renders(world):
    """Платёж — запись регистра, но рождается с номером квитанции своей серии (RCP)."""
    invoice, payment = _paid_invoice(world)

    assert payment.receipt_number.startswith("RCP")

    totals = {"ccy": "UZS", "total": Decimal("112.00")}
    body = render_receipt_body(payment, totals, "UZS", company_template_for(None, "RECEIPT"))
    assert "подтверждается получение оплаты" in body
    assert invoice.number in body, "квитанция ссылается на счёт"
    assert "Руководитель:" in body


@pytest.mark.django_db
def test_delivery_note_body_renders_from_shipment(world):
    fulfillment = Fulfillment.objects.create(
        deal=world["deal"],
        contract=world["contract"],
        status=FulfillmentStatus.objects.get(code="IN_TRANSIT"),
        shipped_at=timezone.now(),
        carrier="ООО ТрансЛог",
        tracking_number="TRK-42",
    )

    body = render_delivery_note_body(fulfillment, [], "UZS", company_template_for(None, "DELIVERY_NOTE"))

    assert "ООО ТрансЛог" in body
    assert "Отправитель (Поставщик):" in body and "Получатель (Покупатель):" in body
    assert "Груз передан перевозчику" in body


@pytest.mark.django_db
def test_recent_documents_feed_lists_both_artifacts(world, rf):
    _invoice, _payment = _paid_invoice(world)
    Fulfillment.objects.create(
        deal=world["deal"],
        contract=world["contract"],
        status=FulfillmentStatus.objects.get(code="IN_TRANSIT"),
        shipped_at=timezone.now(),
    )
    from crm.services.recent_documents import recent_documents

    request = rf.get("/")
    request.user = world["seller_user"]
    types = {entry["type"] for entry in recent_documents(world["seller_user"], request, limit=20)}
    assert "receipt" in types
    assert "delivery_note" in types

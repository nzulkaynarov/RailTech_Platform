"""E3 — снапшот редакции шаблона в документ при выпуске (spec-editable-outgoing-documents).

Документ печатается по той редакции шаблона, что действовала на момент выпуска, и хранит её
у себя — иначе правка шаблона задним числом меняет уже выпущенные договоры и счета. Блоки
(штампы подписей, суммы) остаются живыми данными: замораживается только ТЕКСТ.

Self-contained fixtures (зеркалит test_invoice_lifecycle.py): тесты бегут с --nomigrations,
все lookup-коды сеются здесь.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    SystemRole,
    WorkspaceRole,
)
from crm.models import (
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    DocumentTemplate,
    DocumentTemplateKind,
    FulfillmentStatus,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)
from crm.services.billing import generate_act, generate_invoice_from_contract
from crm.services.document_blocks import frozen_body_for, render_invoice_body
from crm.services.invoice_lifecycle import issue_invoice
from notifications.models import NotificationType


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    for code in ("DRAFT", "CONTRACT_SIGNED", "CLOSED_WON"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    for code in ("DRAFT", "SIGNED", "CANCELLED"):
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "CANCELLED"):
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ("DRAFT", "ISSUED", "SIGNED", "CANCELLED"):
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    FulfillmentStatus.objects.get_or_create(code="PENDING", defaults={"name": "Pending", "sort_order": 10})
    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 10})
    for code, name in (("INVOICE", "Счёт"), ("CONTRACT", "Договор"), ("ACT", "Акт")):
        DocumentTemplateKind.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})


@pytest.fixture
def world(lookups):
    buyer_co = Company.objects.create(
        name="Buyer Co",
        inn="B901",
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    seller_co = Company.objects.create(
        name="Seller Co",
        inn="S901",
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller_user = CustomUser.objects.create_user(email="s@snap.test", username="s@snap.test", password="x")
    CompanyMember.objects.create(
        user=seller_user,
        company=seller_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    SupplierSubscription.objects.create(
        company=seller_co,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=30),
    )
    deal = Deal.objects.create(title="Snap deal", company=buyer_co, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
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
        number="CT-SNAP-901",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    return {"seller_co": seller_co, "seller_user": seller_user, "deal": deal, "contract": contract}


def _company_invoice_template(seller_co, body: str):
    return DocumentTemplate.objects.create(
        company=seller_co,
        kind=DocumentTemplateKind.objects.get(code="INVOICE"),
        name="Наш счёт",
        body_html=body,
        is_active=True,
    )


@pytest.mark.django_db
def test_frozen_body_for_prefers_company_template(world):
    _company_invoice_template(world["seller_co"], "<p>Редакция v1</p>{{doc.totals}}")
    assert "Редакция v1" in frozen_body_for(world["seller_co"], "INVOICE")


@pytest.mark.django_db
def test_issue_freezes_the_template_and_later_edits_do_not_leak(world):
    """Главный инвариант E3: выставленный счёт хранит редакцию времени выставления."""
    template = _company_invoice_template(world["seller_co"], "<p>Редакция v1</p>{{doc.totals}}")
    invoice, err = generate_invoice_from_contract(world["contract"].id, actor=None)
    assert err is None
    assert invoice.frozen_template_body == "", "черновик следует за живым шаблоном"

    invoice, err = issue_invoice(invoice, world["seller_user"])
    assert err is None
    assert "Редакция v1" in invoice.frozen_template_body

    # Правка шаблона задним числом…
    template.body_html = "<p>Редакция v2 — переписанная</p>{{doc.totals}}"
    template.save(update_fields=["body_html"])

    # …не меняет то, что печатает выпущенный документ.
    body = render_invoice_body(
        invoice,
        [],
        {"ccy": "UZS", "total": Decimal("112")},
        "UZS",
        None,
        body_html=invoice.frozen_template_body,
    )
    assert "Редакция v1" in body and "Редакция v2" not in body


@pytest.mark.django_db
def test_act_is_born_with_a_frozen_template(world):
    DocumentTemplate.objects.create(
        company=world["seller_co"],
        kind=DocumentTemplateKind.objects.get(code="ACT"),
        name="Наш акт",
        body_html="<p>Акт v1</p>{{doc.signatures}}",
        is_active=True,
    )
    invoice, _ = generate_invoice_from_contract(world["contract"].id, actor=None)
    invoice, _ = issue_invoice(invoice, world["seller_user"])

    act, err = generate_act(invoice.id, world["seller_user"])

    assert err is None
    assert "Акт v1" in act.frozen_template_body


@pytest.mark.django_db
def test_documents_issued_before_e3_fall_back_to_the_live_template(world):
    """Пустой снапшот (документ до E3) — рендер продолжает читать живой шаблон, как раньше."""
    _company_invoice_template(world["seller_co"], "<p>Живой шаблон</p>{{doc.totals}}")
    invoice, _ = generate_invoice_from_contract(world["contract"].id, actor=None)
    assert invoice.frozen_template_body == ""

    from crm.services.document_blocks import company_template_for

    template = company_template_for(world["seller_co"], "INVOICE")
    body = render_invoice_body(invoice, [], {"ccy": "UZS", "total": Decimal("112")}, "UZS", template)
    assert "Живой шаблон" in body

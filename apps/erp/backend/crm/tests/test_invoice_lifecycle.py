"""Wave C — Invoice DRAFT lifecycle (ERP draft→posted split).

An invoice is now BORN a DRAFT (was auto-ISSUED): the seller reviews it (due_date / notes
editable while DRAFT), then explicitly ISSUES it (renders the PDF, notifies the buyer). A paid
invoice can never be cancelled. Auto-invoice on deal win creates a DRAFT and nudges the seller —
NEVER auto-issues (owner keeps control).

Self-contained fixtures (mirrors test_billing_visibility.py): tests run with --nomigrations, so
every lookup code the flow asserts on is seeded here.
"""

from datetime import date, timedelta
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
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteStatus,
)
from crm.services.billing import generate_invoice_from_contract
from crm.services.invoice_lifecycle import cancel_invoice, issue_invoice, update_invoice_draft
from notifications.models import Notification, NotificationType


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 20})
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


def _company(name, inn, type_code):
    company = Company.objects.create(
        name=name,
        inn=inn,
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, *, can_sell=False, can_buy=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )
    return user


@pytest.fixture
def world(lookups):
    """A buyer, a seller (operational subscription so it may issue/cancel), routed to a
    signed-contract deal. Returns the actors + the DRAFT-able invoice's building blocks."""
    buyer_co = _company("Buyer Co", "B900", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@inv.test", can_buy=True)

    seller_co = _company("Seller Co", "S900", "SUPPLIER")
    seller_user = _member(seller_co, "seller@inv.test", can_sell=True)
    SupplierSubscription.objects.create(
        company=seller_co,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.localdate() + timedelta(days=30),
    )
    deal = Deal.objects.create(title="Inv deal", company=buyer_co, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
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
        number="CT-INV-900",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    return {
        "buyer_co": buyer_co,
        "buyer_user": buyer_user,
        "seller_co": seller_co,
        "seller_user": seller_user,
        "deal": deal,
        "quote": quote,
        "contract": contract,
    }


def _make_draft(world):
    invoice, err = generate_invoice_from_contract(world["contract"].id, actor=None)
    assert err is None, err
    return invoice


# ── 1. Creation from a signed contract → DRAFT (not ISSUED, no issue date, no PDF) ─────


@pytest.mark.django_db
def test_generate_from_contract_creates_draft(world):
    invoice = _make_draft(world)
    assert invoice.status_code == "DRAFT"
    assert invoice.issued_at is None
    assert not invoice.pdf_file  # no legal PDF is rendered for a draft


# ── 2. Issue DRAFT → ISSUED stamps the issue date ─────────────────────────────────────


@pytest.mark.django_db
def test_issue_draft_transitions_to_issued(world):
    invoice = _make_draft(world)
    issued, err = issue_invoice(invoice, world["seller_user"])
    assert err is None, err
    assert issued.status_code == "ISSUED"
    assert issued.issued_at == timezone.localdate()


# ── 3. Re-issuing an already-issued invoice is rejected ───────────────────────────────


@pytest.mark.django_db
def test_reissue_is_rejected(world):
    invoice = _make_draft(world)
    issued, err = issue_invoice(invoice, world["seller_user"])
    assert err is None
    again, err2 = issue_invoice(issued, world["seller_user"])
    assert again is None
    assert err2 == "INVOICE_ALREADY_ISSUED"


# ── 4. Cancel a DRAFT and an ISSUED invoice → CANCELLED ───────────────────────────────


@pytest.mark.django_db
def test_cancel_draft_invoice(world):
    invoice = _make_draft(world)
    cancelled, err = cancel_invoice(invoice, world["seller_user"])
    assert err is None, err
    assert cancelled.status_code == "CANCELLED"


@pytest.mark.django_db
def test_cancel_issued_invoice(world):
    invoice = _make_draft(world)
    issued, _ = issue_invoice(invoice, world["seller_user"])
    cancelled, err = cancel_invoice(issued, world["seller_user"])
    assert err is None, err
    assert cancelled.status_code == "CANCELLED"


@pytest.mark.django_db
def test_cancel_already_cancelled_is_rejected(world):
    invoice = _make_draft(world)
    cancel_invoice(invoice, world["seller_user"])
    again, err = cancel_invoice(invoice, world["seller_user"])
    assert again is None
    assert err == "INVOICE_ALREADY_CANCELLED"


# ── 5. A paid / partially-paid invoice can NOT be cancelled ───────────────────────────


@pytest.mark.django_db
def test_cancel_paid_invoice_is_rejected(world):
    invoice = _make_draft(world)
    issue_invoice(invoice, world["seller_user"])
    invoice.refresh_from_db()
    invoice.amount_paid = Decimal("50")
    invoice.status = InvoiceStatus.objects.get(code="PARTIAL")
    invoice.save(update_fields=["amount_paid", "status"])

    result, err = cancel_invoice(invoice, world["seller_user"])
    assert result is None
    assert err == "INVOICE_CANNOT_CANCEL_PAID"


# ── 6. update_invoice_draft edits due_date/notes only in DRAFT ─────────────────────────


@pytest.mark.django_db
def test_update_draft_changes_due_date(world):
    invoice = _make_draft(world)
    new_due = date(2030, 1, 15)
    updated, err = update_invoice_draft(invoice, world["seller_user"], due_date=new_due, notes="Оплата по факту")
    assert err is None, err
    updated.refresh_from_db()
    assert updated.due_date == new_due
    assert updated.notes == "Оплата по факту"


@pytest.mark.django_db
def test_update_issued_invoice_is_rejected(world):
    invoice = _make_draft(world)
    issued, _ = issue_invoice(invoice, world["seller_user"])
    result, err = update_invoice_draft(issued, world["seller_user"], due_date=date(2030, 1, 15))
    assert result is None
    assert err == "INVOICE_NOT_EDITABLE"


# ── 7. Viewer/permission gates ────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_buyer_cannot_issue_invoice(world):
    invoice = _make_draft(world)
    result, err = issue_invoice(invoice, world["buyer_user"])
    assert result is None
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


# ── 8. Auto-invoice on CLOSED_WON → DRAFT + seller notification (never auto-ISSUED) ────


@pytest.mark.django_db
def test_auto_invoice_on_closed_won_creates_draft_and_notifies_seller(world):
    from crm.tasks import auto_invoice_on_closed_won

    deal = world["deal"]
    auto_invoice_on_closed_won.apply(args=[deal.id]).get()

    invoice = Invoice.objects.get(deal=deal)
    assert invoice.status_code == "DRAFT"  # NOT auto-issued
    assert invoice.issued_at is None

    notif = Notification.objects.filter(user=world["seller_user"], deal=deal).first()
    assert notif is not None, "seller was not nudged to issue the draft invoice"
    assert "выставьте" in notif.message

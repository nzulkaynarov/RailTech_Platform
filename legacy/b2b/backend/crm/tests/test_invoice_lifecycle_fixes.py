"""Fix-wave F1 — invoice-lifecycle correctness (adversarial audit of Wave C).

Covers the block-I defects:
  I-1  record_payment rejects a DRAFT invoice → INVOICE_NOT_ISSUED (no "zombie PAID").
  I-2  update_invoice_draft is seller-gated (buyer / non-routed seller cannot edit a draft).
  I-3  the invoice list queryset HIDES DRAFT from the buyer, but shows ISSUED to both sides.
  I-4  generate_invoice_from_contract ignores CANCELLED invoices → re-invoicing works after cancel.
  I-5  a bogus contract/invoice id resolves to NOT_FOUND (404), never a 500.

Self-contained fixtures (mirrors test_invoice_lifecycle.py / test_billing_visibility.py): tests
run with --nomigrations, so every lookup code the flow asserts on is seeded here.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SupplierSubscription,
    SystemRole,
    VerificationStatus,
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
    InvoiceStatus,
    Quote,
    QuoteStatus,
)
from crm.serializers import ContractSerializer
from crm.services.billing import generate_invoice_from_contract, record_payment
from crm.services.invoice_lifecycle import cancel_invoice, issue_invoice, update_invoice_draft

_INVOICES_URL = "/api/v1/crm/invoices/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
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


def _company(name, inn, type_code, *, kyc=None):
    company = Company.objects.create(
        name=name,
        inn=inn,
        verification_status=(VerificationStatus.objects.get(code=kyc) if kyc else None),
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


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _ids(resp):
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {row["id"] for row in rows}


@pytest.fixture
def world(lookups):
    """A buyer, a routed seller (KYC L2 + operational subscription), an UNRELATED seller, and a
    signed-contract deal ready to be invoiced."""
    buyer_co = _company("Buyer Co", "B901", "CLIENT", kyc="L2_VERIFIED")
    buyer_user = _member(buyer_co, "buyer@invfix.test", can_buy=True)

    seller_co = _company("Seller Co", "S901", "SUPPLIER", kyc="L2_VERIFIED")
    seller_user = _member(seller_co, "seller@invfix.test", can_sell=True)
    SupplierSubscription.objects.create(
        company=seller_co,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.now().date() + timedelta(days=30),
    )

    other_co = _company("Other Seller Co", "O901", "SUPPLIER", kyc="L2_VERIFIED")
    other_user = _member(other_co, "other@invfix.test", can_sell=True)

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
        number="CT-INVFIX-901",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    return {
        "buyer_co": buyer_co,
        "buyer_user": buyer_user,
        "seller_co": seller_co,
        "seller_user": seller_user,
        "other_user": other_user,
        "deal": deal,
        "quote": quote,
        "contract": contract,
    }


def _make_draft(world):
    invoice, err = generate_invoice_from_contract(world["contract"].id, actor=None)
    assert err is None, err
    return invoice


# ── I-1: record_payment rejects a DRAFT invoice (no zombie PAID) ──────────────────────


@pytest.mark.django_db
def test_record_payment_on_draft_is_rejected(world):
    invoice = _make_draft(world)
    assert invoice.status_code == "DRAFT"
    result, err = record_payment(invoice.id, actor=world["buyer_user"], amount=Decimal("112"), paid_at=date.today())
    assert result is None
    assert err == "INVOICE_NOT_ISSUED"
    invoice.refresh_from_db()
    assert invoice.status_code == "DRAFT"  # untouched — no zombie PAID
    assert invoice.amount_paid == Decimal("0")


@pytest.mark.django_db
def test_record_payment_on_issued_is_allowed(world):
    """Control: once ISSUED, the buyer can pay it (DRAFT gate does not over-block)."""
    invoice = _make_draft(world)
    issue_invoice(invoice, world["seller_user"])
    invoice.refresh_from_db()
    payment, err = record_payment(invoice.id, actor=world["buyer_user"], amount=Decimal("112"), paid_at=date.today())
    assert err is None, err
    assert payment is not None
    invoice.refresh_from_db()
    assert invoice.status_code == "PAID"


@pytest.mark.django_db
def test_record_payment_on_paid_is_rejected(world):
    """Over-payment guard: a fully PAID invoice accepts no further money."""
    invoice = _make_draft(world)
    issue_invoice(invoice, world["seller_user"])
    invoice.refresh_from_db()
    record_payment(invoice.id, actor=world["buyer_user"], amount=Decimal("112"), paid_at=date.today())
    result, err = record_payment(
        invoice.id, actor=world["buyer_user"], amount=Decimal("50"), paid_at=date.today(), reference="second"
    )
    assert result is None
    assert err == "INVOICE_ALREADY_PAID"


# ── I-2: update_invoice_draft is seller-gated ─────────────────────────────────────────


@pytest.mark.django_db
def test_buyer_cannot_update_invoice_draft(world):
    invoice = _make_draft(world)
    result, err = update_invoice_draft(invoice, world["buyer_user"], due_date=date(2030, 1, 1))
    assert result is None
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


@pytest.mark.django_db
def test_unrouted_seller_cannot_update_invoice_draft(world):
    invoice = _make_draft(world)
    result, err = update_invoice_draft(invoice, world["other_user"], due_date=date(2030, 1, 1))
    assert result is None
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


@pytest.mark.django_db
def test_routed_seller_can_update_invoice_draft(world):
    """Control: the owning seller can still edit its own draft."""
    invoice = _make_draft(world)
    updated, err = update_invoice_draft(invoice, world["seller_user"], due_date=date(2030, 1, 1), notes="hi")
    assert err is None, err
    updated.refresh_from_db()
    assert updated.due_date == date(2030, 1, 1)
    assert updated.notes == "hi"


# ── I-3: DRAFT is hidden from the buyer, shown to the seller; ISSUED visible to both ──


@pytest.mark.django_db
def test_buyer_queryset_hides_draft_shows_issued(world):
    draft = _make_draft(world)
    buyer_client = _api(world["buyer_user"])

    resp = buyer_client.get(_INVOICES_URL)
    assert resp.status_code == 200
    assert draft.id not in _ids(resp), "buyer must not see a seller's DRAFT invoice"

    issue_invoice(draft, world["seller_user"])
    resp2 = buyer_client.get(_INVOICES_URL)
    assert resp2.status_code == 200
    assert draft.id in _ids(resp2), "buyer must see the invoice once it is ISSUED"


@pytest.mark.django_db
def test_seller_queryset_includes_own_draft(world):
    draft = _make_draft(world)
    resp = _api(world["seller_user"]).get(_INVOICES_URL)
    assert resp.status_code == 200
    assert draft.id in _ids(resp), "the owning seller must see its own DRAFT invoice"


@pytest.mark.django_db
def test_unrelated_seller_never_sees_draft(world):
    draft = _make_draft(world)
    resp = _api(world["other_user"]).get(_INVOICES_URL)
    assert resp.status_code == 200
    assert draft.id not in _ids(resp)


# ── I-4: re-invoicing works after a cancellation (CANCELLED ignored) ──────────────────


@pytest.mark.django_db
def test_reinvoice_after_cancel_creates_new_invoice(world):
    first = _make_draft(world)
    cancelled, err = cancel_invoice(first, world["seller_user"])
    assert err is None, err
    assert cancelled.status_code == "CANCELLED"

    second, err2 = generate_invoice_from_contract(world["contract"].id, actor=None)
    assert err2 is None, err2
    assert second is not None
    assert second.id != first.id, "a cancelled invoice must not be re-surfaced as the live one"
    assert second.status_code == "DRAFT"


@pytest.mark.django_db
def test_generate_returns_live_invoice_when_one_exists(world):
    """Control: idempotency still holds for a LIVE invoice — the same one is returned."""
    first = _make_draft(world)
    again, err = generate_invoice_from_contract(world["contract"].id, actor=None)
    assert err is None, err
    assert again.id == first.id


# ── I-4 / III-3: Contract.invoice_id reflects the live invoice, null after cancel ─────


@pytest.mark.django_db
def test_contract_serializer_invoice_id_tracks_live_invoice(world):
    contract = world["contract"]
    assert ContractSerializer(contract).data["invoice_id"] is None

    invoice = _make_draft(world)
    assert ContractSerializer(contract).data["invoice_id"] == invoice.id

    cancel_invoice(invoice, world["seller_user"])
    assert ContractSerializer(contract).data["invoice_id"] is None, "cancelled invoice must not gate the button"


# ── I-5: a bogus id resolves to NOT_FOUND (404), never a 500 ──────────────────────────


@pytest.mark.django_db
def test_generate_invoice_bad_contract_id_returns_not_found(world):
    result, err = generate_invoice_from_contract(999999, actor=None)
    assert result is None
    assert err == "NOT_FOUND"


@pytest.mark.django_db
def test_generate_from_contract_endpoint_bad_id_is_404(world):
    resp = _api(world["seller_user"]).post(
        "/api/v1/crm/invoices/generate-from-contract/", {"contract_id": 999999}, format="json"
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "NOT_FOUND"


@pytest.mark.django_db
def test_record_payment_bad_invoice_id_returns_not_found(world):
    result, err = record_payment(999999, actor=world["buyer_user"], amount=Decimal("10"), paid_at=date.today())
    assert result is None
    assert err == "NOT_FOUND"

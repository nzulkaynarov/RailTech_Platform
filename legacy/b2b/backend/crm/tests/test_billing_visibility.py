"""WP-1 (P0-1) — billing documents are visible to BOTH sides of a deal.

Regression: a member of a SELLER company routed to a deal (DealSellerRouting) could
not see that deal's contract / invoice / act / payment / fulfillment when the SPA
context defaulted to BUYER (X-Active-Context: BUYER) — e.g. after landing from the
dashboard. The billing viewsets called ``seller_visible_deal_ids(user, request)``,
which returns None outside a SELLER context, so the seller fell into the
buyer-own-company branch and saw zero of its routed deals' billing records.

The fix UNIONS the two scopes in every billing get_queryset, independent of the
context header, while KEEPING the seller side confined to ROUTED deals only
(hidden competition, ADR-0003 §5): a seller never sees an unrelated buyer's docs.
"""

from datetime import timedelta
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
    Act,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Payment,
    Quote,
    QuoteStatus,
)

# One list endpoint per billing model — the get_queryset under test.
_ENDPOINTS = {
    "contract": "/api/v1/crm/contracts/",
    "invoice": "/api/v1/crm/invoices/",
    "payment": "/api/v1/crm/payments/",
    "act": "/api/v1/crm/acts/",
    "fulfillment": "/api/v1/crm/fulfillments/",
}
_DOC_TYPES = list(_ENDPOINTS)


@pytest.fixture
def lookups(db):
    """Seed every code the flow asserts on (--nomigrations skips the data migrations)."""
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L1_UNVERIFIED", defaults={"name": "L1", "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 20})
    for code in ("DRAFT", "CONTRACT_SIGNED", "CLOSED_WON", "CLOSED_LOST"):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    for code in ("DRAFT", "PENDING_CLIENT", "PENDING_MANAGER", "SIGNED", "CANCELLED"):
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    InvoiceStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Issued", "sort_order": 10})
    ActStatus.objects.get_or_create(code="ISSUED", defaults={"name": "Issued", "sort_order": 10})
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


def _api(user, ctx=None):
    client = APIClient()
    creds = {"HTTP_AUTHORIZATION": f"Bearer {RefreshToken.for_user(user).access_token}"}
    if ctx:
        creds["HTTP_X_ACTIVE_CONTEXT"] = ctx
    client.credentials(**creds)
    return client


def _ids(resp):
    data = resp.json()
    rows = data["results"] if isinstance(data, dict) and "results" in data else data
    return {row["id"] for row in rows}


@pytest.fixture
def world(lookups):
    """A buyer, a routed seller (KYC L2 + operational subscription so it can also
    sign), an UNRELATED seller (routed elsewhere), a platform admin, a non-member."""
    buyer_co = _company("Buyer Co", "B100", "CLIENT", kyc="L2_VERIFIED")
    buyer_user = _member(buyer_co, "buyer@bill.test", can_buy=True)

    seller_co = _company("Seller Co", "S100", "SUPPLIER", kyc="L2_VERIFIED")
    seller_user = _member(seller_co, "seller@bill.test", can_sell=True)
    SupplierSubscription.objects.create(
        company=seller_co,
        plan="PREMIUM",
        status="ACTIVE",
        valid_until=timezone.now().date() + timedelta(days=30),
    )

    # A competing seller — a real seller (is_seller True) but NOT routed to our deal.
    other_co = _company("Other Seller Co", "O100", "SUPPLIER", kyc="L2_VERIFIED")
    other_user = _member(other_co, "other@bill.test", can_sell=True)

    # Platform admin: SystemRole ADMIN with NO active membership → is_platform_admin.
    admin_user = CustomUser.objects.create_user(
        email="admin@bill.test", username="admin@bill.test", password="x", role=SystemRole.objects.get(code="ADMIN")
    )
    # Authenticated user with no memberships and no admin role → sees nothing.
    nonmember_user = CustomUser.objects.create_user(
        email="nobody@bill.test", username="nobody@bill.test", password="x", role=SystemRole.objects.get(code="USER")
    )
    return {
        "buyer_co": buyer_co,
        "buyer_user": buyer_user,
        "seller_co": seller_co,
        "seller_user": seller_user,
        "other_co": other_co,
        "other_user": other_user,
        "admin_user": admin_user,
        "nonmember_user": nonmember_user,
    }


def _quote(deal):
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )


@pytest.fixture
def billing_docs(world):
    """A deal owned by the buyer and ROUTED to the seller, with one of every billing
    document. Returns {doc_type: id}."""
    deal = Deal.objects.create(
        title="Billed deal", company=world["buyer_co"], stage=DealStage.objects.get(code="DRAFT")
    )
    DealSellerRouting.objects.create(deal=deal, seller_company=world["seller_co"])
    quote = _quote(deal)

    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-BILL-001",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("112"),
    )
    invoice = Invoice.objects.create(
        deal=deal,
        contract=contract,
        number="INV-BILL-001",
        status=InvoiceStatus.objects.get(code="ISSUED"),
        total_incl_vat=Decimal("112"),
    )
    payment = Payment.objects.create(invoice=invoice, amount=Decimal("112"), paid_at=timezone.now().date())
    act = Act.objects.create(
        deal=deal,
        contract=contract,
        invoice=invoice,
        number="ACT-BILL-001",
        status=ActStatus.objects.get(code="ISSUED"),
        total_amount=Decimal("112"),
    )
    fulfillment = Fulfillment.objects.create(
        deal=deal, contract=contract, status=FulfillmentStatus.objects.get(code="PENDING")
    )
    return {
        "contract": contract.id,
        "invoice": invoice.id,
        "payment": payment.id,
        "act": act.id,
        "fulfillment": fulfillment.id,
    }


# ── 1. Regression: routed seller sees the contract in BUYER context ───────────


def test_routed_seller_sees_contract_in_buyer_context_regression(world, billing_docs):
    """The reported bug: from the dashboard the SPA context defaults to BUYER, yet a
    routed seller must still see the deal's contract (previously it saw none)."""
    resp = _api(world["seller_user"], "BUYER").get(_ENDPOINTS["contract"])
    assert resp.status_code == 200
    assert billing_docs["contract"] in _ids(resp)


def test_routed_seller_sees_contract_in_seller_context(world, billing_docs):
    """Control: the seller also sees it in its native SELLER context (unchanged)."""
    resp = _api(world["seller_user"], "SELLER").get(_ENDPOINTS["contract"])
    assert resp.status_code == 200
    assert billing_docs["contract"] in _ids(resp)


# ── 2. Buyer sees its own contract in either context ──────────────────────────


def test_buyer_sees_own_contract_in_both_contexts(world, billing_docs):
    for ctx in ("BUYER", "SELLER", None):
        resp = _api(world["buyer_user"], ctx).get(_ENDPOINTS["contract"])
        assert resp.status_code == 200
        assert billing_docs["contract"] in _ids(resp), f"buyer lost own contract at ctx={ctx}"


# ── 3 & 4. Both sides see EVERY billing doc; an unrelated seller sees none ─────


@pytest.mark.parametrize("doc_type", _DOC_TYPES)
def test_both_sides_see_billing_doc_in_both_contexts(world, billing_docs, doc_type):
    """The core union: buyer AND routed seller see contract/invoice/payment/act/
    fulfillment regardless of the X-Active-Context header."""
    doc_id = billing_docs[doc_type]
    url = _ENDPOINTS[doc_type]
    for viewer_key in ("seller_user", "buyer_user"):
        for ctx in ("BUYER", "SELLER", None):
            resp = _api(world[viewer_key], ctx).get(url)
            assert resp.status_code == 200
            assert doc_id in _ids(resp), f"{doc_type} not visible to {viewer_key} ctx={ctx}"


@pytest.mark.parametrize("doc_type", _DOC_TYPES)
def test_unrelated_seller_never_sees_billing_doc(world, billing_docs, doc_type):
    """Hidden competition (ADR-0003 §5): a seller NOT routed to the deal (and not a
    member of its buyer company) sees none of its billing docs, in any context."""
    doc_id = billing_docs[doc_type]
    url = _ENDPOINTS[doc_type]
    for ctx in ("BUYER", "SELLER", None):
        resp = _api(world["other_user"], ctx).get(url)
        assert resp.status_code == 200
        assert doc_id not in _ids(resp), f"{doc_type} leaked to unrelated seller ctx={ctx}"


# ── 5. Platform admin sees all; a non-member sees nothing ─────────────────────


def test_platform_admin_sees_all_billing_docs(world, billing_docs):
    for doc_type, url in _ENDPOINTS.items():
        resp = _api(world["admin_user"], "BUYER").get(url)
        assert resp.status_code == 200
        assert billing_docs[doc_type] in _ids(resp), f"admin cannot see {doc_type}"


def test_non_member_sees_no_billing_docs(world, billing_docs):
    for doc_type, url in _ENDPOINTS.items():
        for ctx in ("BUYER", "SELLER", None):
            resp = _api(world["nonmember_user"], ctx).get(url)
            assert resp.status_code == 200
            assert billing_docs[doc_type] not in _ids(resp), f"non-member saw {doc_type} ctx={ctx}"


# ── 6. E2E: routed seller signs the contract from the (BUYER-context) dashboard ─


def test_routed_seller_signs_contract_from_buyer_context_closes_deal(world):
    """Acceptance: the seller opens «Контракты» from the dashboard (BUYER context),
    sees the client-signed contract in the list, signs it, and the deal auto-closes
    as CLOSED_WON (contract fully signed → _finalize_if_signed dispatch)."""
    deal = Deal.objects.create(
        title="Sign deal", company=world["buyer_co"], stage=DealStage.objects.get(code="CONTRACT_SIGNED")
    )
    DealSellerRouting.objects.create(deal=deal, seller_company=world["seller_co"])
    quote = _quote(deal)
    quote.prepared_by = world["seller_user"]
    quote.save(update_fields=["prepared_by"])
    # Client has already signed → the contract awaits the seller (manager) signature.
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-SIGN-001",
        status=ContractStatus.objects.get(code="PENDING_MANAGER"),
        total_amount=Decimal("112"),
        client_signer=world["buyer_user"],
        client_signed_at=timezone.now(),
    )

    seller_client = _api(world["seller_user"], "BUYER")
    # It must appear in the list even though the SPA context is BUYER (the regression).
    listed = seller_client.get(_ENDPOINTS["contract"])
    assert listed.status_code == 200
    assert contract.id in _ids(listed), "routed seller cannot see the contract to sign it"

    # Sign as the seller-side manager (action is IsAuthenticated; service binds to routing).
    signed = seller_client.post(f"/api/v1/crm/contracts/{contract.id}/sign-manager/")
    assert signed.status_code == 200, signed.content

    contract.refresh_from_db()
    deal.refresh_from_db()
    assert contract.status_code == "SIGNED"
    assert deal.stage.code == "CLOSED_WON"


# ── 7. Object-level parity: DETAIL retrieve works for a routed seller in BUYER ──
# context too. WP-1 fixed the LIST get_queryset; the object permission
# (core/permissions.py IsCompanyMemberOrPlatformAdmin → seller_can_access_deal) was
# still context-gated, so GET /contracts/{id}/ and the PDF downloads 403'd off the
# X-Active-Context header. Fixed centrally with force=True (routing boundary kept).


def test_routed_seller_retrieves_contract_detail_in_buyer_context(world, billing_docs):
    """A routed seller can OPEN (detail retrieve) the contract it sees in the list,
    even under BUYER context — so the ContractsPage panel / PDF download don't 403."""
    url = f"{_ENDPOINTS['contract']}{billing_docs['contract']}/"
    resp = _api(world["seller_user"], "BUYER").get(url)
    assert resp.status_code == 200
    assert resp.json()["id"] == billing_docs["contract"]


@pytest.mark.parametrize("ctx", ["BUYER", "SELLER", None])
def test_unrelated_seller_cannot_retrieve_contract_detail(world, billing_docs, ctx):
    """Routing boundary preserved at the object level: a seller NOT routed to the
    deal never reaches the contract detail, in any context (403/404, never 200)."""
    url = f"{_ENDPOINTS['contract']}{billing_docs['contract']}/"
    resp = _api(world["other_user"], ctx).get(url)
    assert resp.status_code in (403, 404), f"unrelated seller reached contract detail ctx={ctx}"

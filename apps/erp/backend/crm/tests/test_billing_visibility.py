"""WP-1 (P0-1) — billing documents are visible to BOTH sides of a deal.

The seller of every deal is the own company (BUSINESS §3.3, M1-ERP-02 wave 3): its staff see every
contract / invoice / act / payment / fulfillment; the buyer side (buyer accounts until M2-ERP-01)
sees its own company's deals only; an outsider sees nothing. The original regression — a seller
landing in the BUYER context of the SPA saw zero billing records — is gone together with the
context header: visibility depends only on who the user is.
"""

from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
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


def _company(name, inn, type_code):
    company = Company.objects.create(
        name=name,
        inn=inn,
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
    """A buyer, own-company staff (so it can also sign), an outsider from another client company,
    a platform admin, a non-member."""
    buyer_co = _company("Buyer Co", "B100", "CLIENT")
    buyer_user = _member(buyer_co, "buyer@bill.test", can_buy=True)

    seller_co = _company("Own Co", "S100", "SUPPLIER")
    seller_user = _member(seller_co, "seller@bill.test", can_sell=True)

    # An outsider — a member of ANOTHER client company: neither staff nor this deal's buyer.
    other_co = _company("Other Client Co", "O100", "CLIENT")
    other_user = _member(other_co, "other@bill.test", can_buy=True)

    # Platform admin: SystemRole ADMIN with NO active membership → is_superuser.
    admin_user = CustomUser.objects.create_user(
        is_superuser=True,
        email="admin@bill.test",
        username="admin@bill.test",
        password="x",
        role=SystemRole.objects.get(code="ADMIN"),
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
    """A deal owned by the buyer, with one of every billing document. Returns {doc_type: id}."""
    deal = Deal.objects.create(
        title="Billed deal", company=world["buyer_co"], stage=DealStage.objects.get(code="DRAFT")
    )
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
    payment = Payment.objects.create(invoice=invoice, amount=Decimal("112"), paid_at=timezone.localdate())
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


# ── 1. Own-company staff see every billing doc; the buyer sees its own deal's ──


@pytest.mark.parametrize("doc_type", _DOC_TYPES)
def test_staff_and_buyer_see_billing_doc(world, billing_docs, doc_type):
    doc_id = billing_docs[doc_type]
    for viewer_key in ("seller_user", "buyer_user"):
        resp = _api(world[viewer_key]).get(_ENDPOINTS[doc_type])
        assert resp.status_code == 200
        assert doc_id in _ids(resp), f"{doc_type} not visible to {viewer_key}"


def test_staff_see_billing_of_every_client(world, billing_docs):
    """Single seller: a contract on ANOTHER client's deal is the same company's document."""
    other_deal = Deal.objects.create(
        title="Other client deal", company=world["other_co"], stage=DealStage.objects.get(code="DRAFT")
    )
    other_contract = Contract.objects.create(
        deal=other_deal,
        quote=_quote(other_deal),
        number="CT-BILL-002",
        status=ContractStatus.objects.get(code="SIGNED"),
        total_amount=Decimal("1"),
    )
    staff_ids = _ids(_api(world["seller_user"]).get(_ENDPOINTS["contract"]))
    assert {billing_docs["contract"], other_contract.id} <= staff_ids
    # …while each buyer sees only its own company's contract.
    assert other_contract.id not in _ids(_api(world["buyer_user"]).get(_ENDPOINTS["contract"]))


# ── 2. An outsider sees none ──────────────────────────────────────────────────


@pytest.mark.parametrize("doc_type", _DOC_TYPES)
def test_outsider_never_sees_billing_doc(world, billing_docs, doc_type):
    """A member of another client company (not staff, not this deal's buyer) sees none."""
    resp = _api(world["other_user"]).get(_ENDPOINTS[doc_type])
    assert resp.status_code == 200
    assert billing_docs[doc_type] not in _ids(resp), f"{doc_type} leaked to an outsider"


# ── 3. Platform admin sees all; a non-member sees nothing ─────────────────────


def test_platform_admin_sees_all_billing_docs(world, billing_docs):
    for doc_type, url in _ENDPOINTS.items():
        resp = _api(world["admin_user"]).get(url)
        assert resp.status_code == 200
        assert billing_docs[doc_type] in _ids(resp), f"admin cannot see {doc_type}"


def test_non_member_sees_no_billing_docs(world, billing_docs):
    for doc_type, url in _ENDPOINTS.items():
        resp = _api(world["nonmember_user"]).get(url)
        assert resp.status_code == 200
        assert billing_docs[doc_type] not in _ids(resp), f"non-member saw {doc_type}"


# ── 4. E2E: staff signs the contract from the registry and the deal closes ────


def test_staff_signs_contract_from_registry_closes_deal(world):
    """Acceptance: the staff member opens «Контракты», sees the client-signed contract, signs it,
    and the deal auto-closes as CLOSED_WON (contract fully signed → _finalize_if_signed)."""
    deal = Deal.objects.create(
        title="Sign deal", company=world["buyer_co"], stage=DealStage.objects.get(code="CONTRACT_SIGNED")
    )
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

    seller_client = _api(world["seller_user"])
    listed = seller_client.get(_ENDPOINTS["contract"])
    assert listed.status_code == 200
    assert contract.id in _ids(listed), "staff cannot see the contract to sign it"

    signed = seller_client.post(f"/api/v1/crm/contracts/{contract.id}/sign-manager/")
    assert signed.status_code == 200, signed.content

    contract.refresh_from_db()
    deal.refresh_from_db()
    assert contract.status_code == "SIGNED"
    assert deal.stage.code == "CLOSED_WON"


# ── 5. Object-level parity: DETAIL retrieve ───────────────────────────────────


def test_staff_retrieves_contract_detail(world, billing_docs):
    """Staff can OPEN (detail retrieve) the contract it sees in the list — so the ContractsPage
    panel / PDF download don't 403."""
    url = f"{_ENDPOINTS['contract']}{billing_docs['contract']}/"
    resp = _api(world["seller_user"]).get(url)
    assert resp.status_code == 200
    assert resp.json()["id"] == billing_docs["contract"]


def test_outsider_cannot_retrieve_contract_detail(world, billing_docs):
    url = f"{_ENDPOINTS['contract']}{billing_docs['contract']}/"
    resp = _api(world["other_user"]).get(url)
    assert resp.status_code in (403, 404), "outsider reached contract detail"

"""Permission-guard integration tests for CRM business services.

Covers the service call sites where CompanyRole permissions are enforced:

    quote.send   → can_send_quote_to_client (services/quotes.py)
    contract.sign → sign_contract_by_manager
    finance.payment → record_payment (services/billing.py)

Each guard is tested in three modes:
    WITH perm  → member that has the CompanyRole permission — PASSES
    WITHOUT perm → member that lacks the permission — DENIED
    Legacy path → own-company staff: the WorkspaceRole / can_sell fallback is GONE (M1-ERP-05 —
                  no role, no permission).

The buyer side (sign_contract_by_client / record_payment / approve_quote by a client-company member)
left ERP with the buyer accounts (FIX-13): the client acts only in the portal.
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Contract, ContractStatus, Deal, DealStage, Invoice, InvoiceStatus, Quote, QuoteStatus
from crm.services.billing import record_payment
from crm.services.contracts import sign_contract_by_manager
from crm.services.quotes import QuoteLifecycleService, can_send_quote_to_client
from master_data.models import Country, Currency

# ─── helpers ──────────────────────────────────────────────────────────────────


def _ws(code):
    """Get-or-create a WorkspaceRole by code (avoids conflicts across tests)."""
    role, _ = WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    return role


def _make_user(email):
    return CustomUser.objects.create_user(
        email=email,
        username=email,
        password="pw",
        is_active=True,
    )


def _make_member(user, company, *, roles=(), can_sell=True, is_primary=False):
    return CompanyMember.objects.create(
        user=user,
        company=company,
        role=_ws("MEMBER"),
        company_roles=list(roles),
        is_primary=is_primary,
        is_active=True,
        can_sell=can_sell,
    )


# ─── shared lookups fixture ────────────────────────────────────────────────────


@pytest.fixture
def lookups(db):
    """Seed the DB rows that services resolve via .get() (IRON RULE 1)."""
    for code in ["DRAFT", "RFQ_OPEN", "CALCULATING", "QUOTE_SENT", "CONTRACT_SIGNED"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code, name in [
        ("DRAFT", "Draft"),
        ("PENDING_TRADE_REVIEW", "Pending Trade"),
        ("PENDING_APPROVAL", "Pending Approval"),
        ("READY_TO_SEND", "Ready to Send"),
        ("SENT", "Sent"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    for code in ["DRAFT", "PENDING_CLIENT", "PENDING_MANAGER", "SIGNED", "CANCELLED"]:
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "CANCELLED"]:
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
    Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "$", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    for code in ["INFO", "SUCCESS", "WARNING", "ERROR"]:
        from notifications.models import NotificationType

        NotificationType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


@pytest.fixture
def buyer_company(lookups):
    company = Company.objects.create(
        name="Buyer Co",
        inn="1110000001",
    )
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return company


@pytest.fixture
def seller_company(lookups):
    company = Company.objects.create(
        name="Seller Co",
        inn="2220000001",
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    return company


@pytest.fixture
def deal(lookups, buyer_company, seller_company):
    deal = Deal.objects.create(
        title="PG Deal",
        company=buyer_company,
        stage=DealStage.objects.get(code="CALCULATING"),
    )
    # The seller of every deal is the own company (seller_company) — no routing row needed.
    return deal


def _ready_to_send_quote(deal, prepared_by):
    """Create a READY_TO_SEND Quote anchored to `prepared_by` (the seller)."""
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="READY_TO_SEND"),
        prepared_by=prepared_by,
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )


def _sent_quote(deal, prepared_by):
    """Create a SENT Quote (prices frozen). A SENT quote means the deal is in QUOTE_SENT — keep
    the fixture consistent with reality (send_to_client moves the deal there), so approve/reject
    can legally advance the FSM (the service now raises on an illegal transition, not swallows)."""
    from django.utils import timezone

    deal.stage = DealStage.objects.get(code="QUOTE_SENT")
    deal.save(update_fields=["stage"])
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="SENT"),
        prepared_by=prepared_by,
        frozen_at=timezone.now(),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )


def _pending_client_contract(deal, quote):
    return Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-TEST-001",
        status=ContractStatus.objects.get(code="PENDING_CLIENT"),
        total_amount=Decimal("112"),
    )


def _issued_invoice(deal, contract):
    return Invoice.objects.create(
        deal=deal,
        contract=contract,
        number="INV-TEST-001",
        status=InvoiceStatus.objects.get(code="ISSUED"),
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1.  can_send_quote_to_client  (quote.send)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_quote_send_with_explicit_perm_passes(lookups, seller_company, deal):
    """Member WITH quote.send CompanyRole permission can send the КП of HIS request (B-008: deal.manager)."""
    seller = _make_user("send_with@seller.test")
    _make_member(seller, seller_company, is_primary=True)
    deal.manager = seller
    deal.save(update_fields=["manager"])
    quote = _ready_to_send_quote(deal, prepared_by=seller)
    # Grant the permission via CompanyRole.
    crole = CompanyRole.objects.create(company=seller_company, name="Sender", permissions=["quote.send"])
    seller.memberships.get(company=seller_company).company_roles.add(crole)

    assert can_send_quote_to_client(seller, quote) is True


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("permissions", "is_manager", "allowed"),
    [
        (["quote.send"], True, True),  # менеджер своей заявки
        (["quote.send"], False, False),  # чужая заявка — 403 (B-008)
        (["quote.send", "quote.review"], False, True),  # директор / «КП на одобрение» full
        (["quote.review"], False, False),  # без quote.send — нельзя никому
        (["quote.review"], True, False),
    ],
)
def test_quote_send_is_checked_per_request_manager(lookups, seller_company, deal, permissions, is_manager, allowed):
    """B-008 (W16-D1-2): `quote.send` даёт отправку КП своей заявки; чужой — только с `quote.review`."""
    seller = _make_user("send_object@seller.test")
    crole = CompanyRole.objects.create(company=seller_company, name="ObjectSender", permissions=permissions)
    _make_member(seller, seller_company, roles=[crole], can_sell=False, is_primary=True)
    author = _make_user("author_object@seller.test")
    _make_member(author, seller_company, can_sell=False, is_primary=True)
    deal.manager = seller if is_manager else author
    deal.save(update_fields=["manager"])
    quote = _ready_to_send_quote(deal, prepared_by=author)

    assert can_send_quote_to_client(seller, quote) is allowed


@pytest.mark.django_db
def test_quote_send_without_perm_denied(lookups, seller_company, deal):
    """Member WITHOUT quote.send perm is denied."""
    seller = _make_user("send_without@seller.test")
    # can_sell=False removes legacy fallback; no CompanyRole means no explicit perm.
    _make_member(seller, seller_company, can_sell=False, is_primary=True)
    quote = _ready_to_send_quote(deal, prepared_by=seller)

    assert can_send_quote_to_client(seller, quote) is False


@pytest.mark.django_db
def test_quote_send_legacy_sales_manager_role_no_longer_grants_send(lookups, seller_company, deal):
    """M1-ERP-05: the SALES_MANAGER WorkspaceRole without a role carrying quote.send is denied."""
    seller = _make_user("send_legacy@seller.test")
    # Set up the legacy workspace role directly (no CompanyRole assigned).
    ws_sales = WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Sales Manager", "sort_order": 20}
    )[0]
    CompanyMember.objects.create(
        user=seller,
        company=seller_company,
        role=ws_sales,
        is_primary=True,
        is_active=True,
        can_sell=True,
    )
    quote = _ready_to_send_quote(deal, prepared_by=seller)

    assert can_send_quote_to_client(seller, quote) is False


@pytest.mark.django_db
def test_quote_send_perm_without_legacy_ws_role_passes(lookups, seller_company, deal):
    """A member assigned only quote.send CompanyRole (no SALES_MANAGER wsrole) can send."""
    seller = _make_user("send_perm_only@seller.test")
    crole = CompanyRole.objects.create(company=seller_company, name="QuoteSender", permissions=["quote.send"])
    # Use MEMBER workspace role — no legacy SALES_MANAGER — but has the CompanyRole perm.
    _make_member(seller, seller_company, roles=[crole], can_sell=False, is_primary=True)
    deal.manager = seller
    deal.save(update_fields=["manager"])
    quote = _ready_to_send_quote(deal, prepared_by=seller)

    assert can_send_quote_to_client(seller, quote) is True


@pytest.mark.django_db
def test_quote_send_null_company_role_non_sales_with_can_sell_denied(lookups, seller_company, deal):
    """A role-less member with a NON-sales WorkspaceRole (LOGIST) and the DEFAULT can_sell=True must
    NOT be granted client-facing send: only the quote.send role permission counts."""
    seller = _make_user("send_logist@seller.test")
    ws_logist = WorkspaceRole.objects.get_or_create(code="LOGIST", defaults={"name": "Logist", "sort_order": 30})[0]
    CompanyMember.objects.create(
        user=seller,
        company=seller_company,
        role=ws_logist,
        is_primary=True,
        is_active=True,
        can_sell=True,
    )  # no roles at all
    quote = _ready_to_send_quote(deal, prepared_by=seller)

    assert can_send_quote_to_client(seller, quote) is False


@pytest.mark.django_db
def test_quote_send_legacy_owner_role_no_longer_grants_send(lookups, seller_company, deal):
    """M1-ERP-05: the OWNER WorkspaceRole without roles is denied (the transitional bridge is gone)."""
    seller = _make_user("send_owner@seller.test")
    ws_owner = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    CompanyMember.objects.create(
        user=seller,
        company=seller_company,
        role=ws_owner,
        is_primary=True,
        is_active=True,
        can_sell=True,
    )
    quote = _ready_to_send_quote(deal, prepared_by=seller)

    assert can_send_quote_to_client(seller, quote) is False


# ═══════════════════════════════════════════════════════════════════════════════
# 2.  sign_contract_by_client  (contract.sign)
# ═══════════════════════════════════════════════════════════════════════════════


# ═══════════════════════════════════════════════════════════════════════════════
# 3.  sign_contract_by_manager  (contract.sign, seller side)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_contract_manager_sign_with_perm_passes(lookups, buyer_company, seller_company, deal):
    """Seller member WITH contract.sign CompanyRole permission can sign as manager.

    The member uses MEMBER workspace role (no SALES_MANAGER/OWNER legacy path),
    but has can_sell=True so the seller-side checks can resolve their seller company. The CompanyRole perm is what bypasses the
    WorkspaceRole check: even a MEMBER can sign contracts when explicitly granted.
    """
    seller = _make_user("msign_seller_perm@s.test")
    crole = CompanyRole.objects.create(company=seller_company, name="ContractManager", permissions=["contract.sign"])
    # can_sell=True is required so the seller-side checks can locate the company.
    seller_member = _make_member(seller, seller_company, can_sell=True, is_primary=True)
    seller_member.company_roles.add(crole)

    quote = _sent_quote(deal, prepared_by=seller)
    # Need PENDING_MANAGER status for manager to sign (client already signed).
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-MSIGN-001",
        status=ContractStatus.objects.get(code="PENDING_MANAGER"),
        total_amount=Decimal("112"),
    )
    result, err = sign_contract_by_manager(contract.id, seller)
    assert err is None, f"Expected success, got error: {err}"
    assert result is not None


@pytest.mark.django_db
def test_contract_manager_sign_without_perm_denied(lookups, buyer_company, seller_company, deal):
    """Seller member WITHOUT contract.sign perm AND without legacy capability is denied.

    No role carrying contract.sign → refused (flags no longer matter for staff).
    """
    seller = _make_user("msign_seller_noperm@s.test")
    # Both flags off: no legacy path, no CompanyRole → neither check passes.
    _make_member(seller, seller_company, can_sell=False, is_primary=True)

    quote = _sent_quote(deal, prepared_by=seller)
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-MSIGN-002",
        status=ContractStatus.objects.get(code="PENDING_MANAGER"),
        total_amount=Decimal("112"),
    )
    result, err = sign_contract_by_manager(contract.id, seller)
    assert err == "MEMBER_REQUIRED_FOR_ACTION"
    assert result is None


@pytest.mark.django_db
def test_contract_manager_sign_legacy_can_sell_no_longer_grants_sign(lookups, buyer_company, seller_company, deal):
    """M1-ERP-05: can_sell=True without a role carrying contract.sign no longer signs for the company."""
    seller = _make_user("msign_seller_legacy@s.test")
    _make_member(seller, seller_company, can_sell=True, is_primary=True)

    quote = _sent_quote(deal, prepared_by=seller)
    contract = Contract.objects.create(
        deal=deal,
        quote=quote,
        number="CT-MSIGN-003",
        status=ContractStatus.objects.get(code="PENDING_MANAGER"),
        total_amount=Decimal("112"),
    )
    result, err = sign_contract_by_manager(contract.id, seller)
    assert err == "MEMBER_REQUIRED_FOR_ACTION"
    assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 4.  record_payment  (payment.record)
# ═══════════════════════════════════════════════════════════════════════════════


@pytest.mark.django_db
def test_record_payment_without_perm_denied(lookups, buyer_company, seller_company, deal):
    """A client-company member (not staff) cannot record a payment: no buyer accounts in ERP (FIX-13)."""
    seller = _make_user("pay_seller2@s.test")
    _make_member(seller, seller_company, is_primary=True)
    quote = _sent_quote(deal, prepared_by=seller)
    contract = _pending_client_contract(deal, quote)
    invoice = _issued_invoice(deal, contract)

    buyer = _make_user("pay_buyer_noperm@b.test")
    _make_member(buyer, buyer_company, is_primary=True)

    from django.utils import timezone

    result, err = record_payment(
        invoice.id,
        buyer,
        amount=Decimal("112"),
        paid_at=timezone.localdate(),
        method="BANK_TRANSFER",
        reference="REF-NOPERM-002",
    )
    assert err == "MEMBER_REQUIRED_FOR_ACTION"
    assert result is None


# ═══════════════════════════════════════════════════════════════════════════════
# 5.  QuoteLifecycleService.approve_quote  (quote.approve, buyer side)
# ═══════════════════════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────────────────
# 6.  P0-1 loop integrity — no silent FSM desync (ADR-0006 Move 0)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_send_kp_from_rfq_open_advances_deal_not_stuck(lookups, buyer_company, seller_company, deal):
    """A КП sent while the deal is in RFQ_OPEN (the request arrives from the portal / CRM handoff) must
    advance the deal to QUOTE_SENT. Previously the FSM error (RFQ_OPEN→QUOTE_SENT is illegal)
    was swallowed → КП marked SENT + emailed while the deal stuck in RFQ_OPEN forever."""
    seller = _make_user("send_rfq_seller@s.test")
    sender = CompanyRole.objects.create(company=seller_company, name="Sender", permissions=["quote.send"])
    _make_member(seller, seller_company, roles=[sender], can_sell=True, is_primary=True)

    deal.stage = DealStage.objects.get(code="RFQ_OPEN")  # real post-submit state
    # A deal in RFQ_OPEN ALWAYS has a client behind it; the bare fixture omitted one, which the B5
    # RECIPIENT_REQUIRED gate now rejects (a КП must not be marked SENT with nobody to send it to).
    deal.client = _make_user("send_rfq_buyer@b.test")
    deal.save(update_fields=["stage", "client"])

    quote = _ready_to_send_quote(deal, prepared_by=seller)
    quote.number = "TEST-KP-001"  # pre-set → skip the document-number minting dependency
    quote.subtotal_excl_vat = Decimal("100")
    quote.vat_amount = Decimal("12")
    quote.total_incl_vat = Decimal("112")
    quote.save()

    QuoteLifecycleService.send_to_client(quote.id, seller)

    deal.refresh_from_db()
    assert deal.stage.code == "QUOTE_SENT", "P0-1: deal must advance through CALCULATING, not stay stuck in RFQ_OPEN"


@pytest.mark.django_db
def test_approve_raises_on_illegal_stage_no_silent_desync(lookups, buyer_company, seller_company, deal):
    """approve_quote must RAISE (not silently 'succeed') when the deal can't legally advance —
    the anti-swallow guarantee. A SENT quote on a deal forced back to CALCULATING can't go to
    CONTRACT_SIGNED, and that must surface, not desync."""
    seller = _make_user("illegal_seller@s.test")
    _make_member(seller, seller_company, is_primary=True)
    quote = _sent_quote(deal, prepared_by=seller)  # this sets deal → QUOTE_SENT
    deal.stage = DealStage.objects.get(code="CALCULATING")  # force an illegal pre-state
    deal.save(update_fields=["stage"])

    buyer = _make_user("illegal_buyer@b.test")
    _make_member(buyer, buyer_company, is_primary=True)

    with pytest.raises(ValueError):
        QuoteLifecycleService.approve_quote(quote.id, buyer)


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Deal ownership / claimable queue (ADR-0006 Move 2)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.django_db
def test_claim_deal_by_staff_then_lock_then_release(lookups, buyer_company, seller_company, deal):
    """A staff member claims an unclaimed deal; a second member can't steal it (claim-lock);
    release returns it to the queue. The world-standard claimable-queue ownership."""
    from crm.services.assignment import claim_deal, release_deal

    def _owner():
        deal.refresh_from_db()
        return deal.assigned_to_id

    seller = _make_user("claim_seller@s.test")
    _make_member(seller, seller_company, can_sell=True, is_primary=True)
    _, err = claim_deal(deal.id, seller)
    # Ownership lives on the deal (ADR-0006 Move 2; the seller is always the own company).
    assert err is None and _owner() == seller.id and deal.assigned_at is not None

    other = _make_user("claim_other@s.test")
    _make_member(other, seller_company, can_sell=True, is_primary=True)
    _, err2 = claim_deal(deal.id, other)
    assert err2 == "DEAL_ALREADY_CLAIMED"  # a teammate owns it — no silent steal

    _, err3 = release_deal(deal.id, seller)
    assert err3 is None and _owner() is None


@pytest.mark.django_db
def test_claim_deal_outsider_denied(lookups, buyer_company, seller_company, deal):
    """A member of another company (not own-company staff) cannot claim it (no cross-tenant grab)."""
    from crm.services.assignment import claim_deal

    seller_anchor = _make_user("claim_anchor@s.test")  # makes seller_company the own company
    _make_member(seller_anchor, seller_company, can_sell=True, is_primary=True)
    other_co = Company.objects.create(
        name="Other Client",
        inn="9990000009",
    )
    other_co.types.add(CompanyType.objects.get(code="CLIENT"))
    outsider = _make_user("outsider@other.test")
    _make_member(outsider, other_co, can_sell=True, is_primary=True)

    _, err = claim_deal(deal.id, outsider)
    assert err == "MEMBER_REQUIRED_FOR_ACTION"

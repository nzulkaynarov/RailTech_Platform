"""
GOLDEN PATH — the single end-to-end regression net for the core business value.

This test drives the WHOLE product story through the real service layer, exactly
as buyer / seller / manager would trigger it from the UI:

    deal moves into CALCULATING  →  manager builds & sends the КП
    →  buyer approves it  →  contract is double-signed  →  invoice is issued
    →  payment is recorded  →  fulfillment accepted  →  deal CLOSED_WON.

If this test is green, the core flow the platform exists for works. If a future
change breaks any step, CI fails BEFORE it reaches production — this is the
"know it's stable" net that replaces clicking through prod by hand.

Runs against the DB via pytest-django (see pyproject.toml). Marked `integration`.
"""

from decimal import Decimal

import pytest
from django.utils import timezone

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from catalog.models import DomainType, ProductStatus, StockStatus
from crm import services as crm_services
from crm.models import (
    ActStatus,
    ContractStatus,
    Deal,
    DealStage,
    FulfillmentStatus,
    InvoiceStatus,
    Quote,
    QuoteItem,
    QuoteStatus,
)
from crm.services.quotes import QuoteCalculationService, QuoteLifecycleService
from master_data.models import Country, Currency, UnitOfMeasure

# ─── Lookup + actor fixtures (self-contained, no shared conftest coupling) ────


@pytest.fixture
def lookups(db):
    """Seed every lookup code the golden path touches.

    Tests run with --nomigrations (pyproject addopts), so the data migration
    that normally seeds these (core/migrations/0002_seed_enterprise_lookups)
    never runs — we recreate the codes the flow asserts on.
    """
    for code in [
        "DRAFT",
        "KYC_PENDING",
        "RFQ_OPEN",
        "SOURCING",
        "CALCULATING",
        "QUOTE_SENT",
        "CONTRACT_SIGNED",
        "CLOSED_WON",
        "CLOSED_LOST",
    ]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code, name in [
        ("DRAFT", "Draft"),
        ("READY_TO_SEND", "Ready"),
        ("SENT", "Sent"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
    Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "$", "sort_order": 10})
    UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "Piece", "sort_order": 10})
    DomainType.objects.get_or_create(
        code="GENERAL_GOODS", defaults={"name": "General goods", "sku_prefix": "GG", "sort_order": 10}
    )
    ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 20})
    StockStatus.objects.get_or_create(code="IN_STOCK", defaults={"name": "In stock", "sort_order": 10})
    # Post-sale status lookups (F5.4) — seeded here because --nomigrations skips the
    # data migration that normally creates these rows.
    for code in ["DRAFT", "PENDING_CLIENT", "PENDING_MANAGER", "SIGNED", "CANCELLED"]:
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "ISSUED", "PARTIAL", "PAID", "OVERDUE", "CANCELLED"]:
        InvoiceStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "ISSUED", "SIGNED", "CANCELLED"]:
        ActStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["PENDING", "SHIPPED", "IN_TRANSIT", "DELIVERED", "ACCEPTED", "DISPUTED"]:
        FulfillmentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _make_company_with_owner(*, name, inn, type_code, email, username):
    user = CustomUser.objects.create_user(
        email=email,
        username=username,
        password="pw",
        is_active=True,
        first_name="T",
        last_name=type_code.title(),
    )
    company = Company.objects.create(
        name=name,
        inn=inn,
        # O3: продавец с платёжными реквизитами — иначе `issue_invoice` не выпустит счёт (он неоплатен).
        bank_account="20208000900001234567",
        mfo="00443",
    )
    company.types.add(CompanyType.objects.get(code=type_code))
    # OWNER membership; can_sell / can_buy default to True (see CompanyMember model).
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_primary=True,
        is_active=True,
    )
    return user, company


@pytest.fixture
def buyer(lookups):
    return _make_company_with_owner(
        name="Golden Buyer LLC",
        inn="7700000001",
        type_code="CLIENT",
        email="g.buyer@example.com",
        username="g_buyer",
    )


@pytest.fixture
def manager(lookups):
    # Platform-side orchestrator. is_superuser bypasses per-company capability
    # checks; role USER keeps the migration-0010 invariant (ADMIN ⇒ no member).
    return CustomUser.objects.create_user(
        email="g.manager@example.com",
        username="g_manager",
        password="pw",
        is_active=True,
        is_staff=True,
        is_superuser=True,
        first_name="T",
        last_name="Manager",
        role=SystemRole.objects.get(code="USER"),
    )


@pytest.fixture
def deal(lookups, buyer, manager):
    buyer_user, buyer_co = buyer
    return Deal.objects.create(
        title="Golden Path Deal",
        company=buyer_co,
        client=buyer_user,
        manager=manager,
        stage=DealStage.objects.get(code="DRAFT"),
    )


def _build_quote_with_items(deal, manager):
    """Manager builds the КП: a draft quote with two priced line items."""
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=manager,
        tax_country=Country.objects.get(code="UZ"),
        vat_rate=Decimal("12.00"),
        # Declare an explicit 1:1 USD→UZS rate (договорной курс) so the КП prices at parity —
        # this test exercises the golden FLOW, not FX conversion. The engine no longer invents a
        # silent rate=1 for a missing rate (KP-01); a КП with an unrated currency is now blocked,
        # so the rate must be stated. (Real FX conversion is covered in the multi-currency tests.)
        fx_manual={"USD": "1"},
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    usd = Currency.objects.get(code="USD")
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="Rail clamp KP-1",
        quantity=10,
        frozen_base_price=Decimal("100.00"),
        frozen_currency=usd,
        # DT1: margin_percent НЕ задаётся ⇒ NULL ⇒ строка наследует маржу КП (20%). Раньше здесь
        # стояли позиционные 20/10, которые движок игнорировал; теперь позиционное значение
        # реально побеждает, поэтому «унаследовать» выражается его ОТСУТСТВИЕМ.
        final_price_excl_vat=Decimal("0"),
    )
    QuoteItem.objects.create(
        quote=quote,
        imported_raw_name="Sleeper bolt M24",
        quantity=4,
        frozen_base_price=Decimal("50.00"),
        frozen_currency=usd,
        final_price_excl_vat=Decimal("0"),
    )
    # Маржа ставится ОДИН раз на весь КП; обе строки выше её наследуют (их margin_percent = NULL).
    quote.margin_percent = Decimal("20.00")
    quote.save(update_fields=["margin_percent"])
    return quote


# ─── THE golden path ──────────────────────────────────────────────────────


@pytest.mark.integration
@pytest.mark.django_db
def test_golden_path_rfq_to_closed_won(deal, buyer, manager):
    """One test, the whole story. Each assert is a step the business depends on."""
    buyer_user, buyer_co = buyer

    # 1-3. Deal advances through the FSM into CALCULATING (DRAFT→SOURCING→CALCULATING).
    for target in ["SOURCING", "CALCULATING"]:
        moved, err = crm_services.transition_deal_stage(deal, target, actor=manager)
        assert err is None, f"transition_deal_stage → {target} failed: {err}"
    deal.refresh_from_db()
    assert deal.stage.code == "CALCULATING"

    # 4. Manager builds the КП and the calculation engine prices it.
    quote = _build_quote_with_items(deal, manager)
    quote = QuoteCalculationService.recalculate_quote(quote.id)
    # F3.8 КП-level margin 20%: 10×(100×1.20) + 4×(50×1.20) = 1200 + 240 = 1440 excl. VAT
    assert quote.subtotal_excl_vat == Decimal("1440.00"), quote.subtotal_excl_vat
    assert quote.vat_amount == Decimal("172.80")  # 12%
    assert quote.total_incl_vat == Decimal("1612.80")

    # 5. КП internally approved (chain is exercised in test_quote_approval_chain)
    #    → READY_TO_SEND, then sent to client → deal QUOTE_SENT, quote SENT, PDF.
    quote.status = QuoteStatus.objects.get(code="READY_TO_SEND")
    quote.save(update_fields=["status"])
    quote = QuoteLifecycleService.send_to_client(quote.id, manager)
    assert quote.status.code == "SENT"
    deal.refresh_from_db()
    assert deal.stage.code == "QUOTE_SENT"

    # 6. Buyer approves the КП → deal CONTRACT_SIGNED.
    quote = QuoteLifecycleService.approve_quote(quote.id, buyer_user)
    assert quote.status.code == "APPROVED"
    deal.refresh_from_db()
    assert deal.stage.code == "CONTRACT_SIGNED"

    # 7. Contract generated from the approved quote, then double-signed.
    contract, err = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    assert err is None, f"generate_contract_from_quote failed: {err}"
    contract, err = crm_services.sign_contract_by_client(contract.id, buyer_user)
    assert err is None, f"sign_contract_by_client failed: {err}"
    assert contract.status_code == "PENDING_MANAGER"
    contract, err = crm_services.sign_contract_by_manager(contract.id, manager)
    assert err is None, f"sign_contract_by_manager failed: {err}"
    assert contract.status_code == "SIGNED"

    # 8. Invoice created (DRAFT) from the signed contract, then explicitly ISSUED (Wave C:
    #    the ERP draft→posted split), then paid in full.
    invoice, err = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
    assert err is None, f"generate_invoice_from_contract failed: {err}"
    assert invoice.status_code == "DRAFT"
    invoice, err = crm_services.issue_invoice(invoice, manager)
    assert err is None, f"issue_invoice failed: {err}"
    assert invoice.status_code == "ISSUED"
    _, err = crm_services.record_payment(
        invoice.id,
        manager,
        amount=invoice.total_incl_vat,
        paid_at=timezone.localdate(),
        manual=True,
    )
    assert err is None, f"record_payment failed: {err}"
    invoice.refresh_from_db()
    assert invoice.status_code == "PAID"

    # 9. Fulfillment accepted → deal auto-closes as CLOSED_WON. Story complete.
    crm_services.ensure_fulfillment(deal)
    _, err = crm_services.update_fulfillment_status(deal.id, manager, "ACCEPTED")
    assert err is None, f"update_fulfillment_status failed: {err}"
    deal.refresh_from_db()
    assert deal.stage.code == "CLOSED_WON"


@pytest.mark.integration
@pytest.mark.django_db
def test_contract_and_billing_events_are_structured(deal, buyer, manager):
    """E1: contracts.py / billing.py producers write machine event_code + params so the
    timeline can be localized on the client (RU action/detail preserved as fallback)."""
    from crm.models import ActivityLog

    buyer_user, _ = buyer

    for target in ["SOURCING", "CALCULATING"]:
        _, err = crm_services.transition_deal_stage(deal, target, actor=manager)
        assert err is None
    quote = _build_quote_with_items(deal, manager)
    QuoteCalculationService.recalculate_quote(quote.id)
    quote.status = QuoteStatus.objects.get(code="READY_TO_SEND")
    quote.save(update_fields=["status"])
    quote = QuoteLifecycleService.send_to_client(quote.id, manager)
    quote = QuoteLifecycleService.approve_quote(quote.id, buyer_user)

    # contracts.py — contract.created + both signature sides.
    contract, err = crm_services.generate_contract_from_quote(quote.id, actor=manager)
    assert err is None
    # approve_quote auto-materializes a contract (Move 0), so this may log twice — take the latest.
    created = ActivityLog.objects.filter(event_code="contract.created", deal=deal).order_by("-id").first()
    assert created.event_params == {"number": contract.number, "deal_id": deal.id}

    contract, err = crm_services.sign_contract_by_client(contract.id, buyer_user)
    assert err is None
    signed_client = ActivityLog.objects.filter(event_code="contract.signed_client", deal=deal).order_by("-id").first()
    assert signed_client.event_params == {"number": contract.number, "deal_id": deal.id, "manual": True}

    contract, err = crm_services.sign_contract_by_manager(contract.id, manager)
    assert err is None
    signed_manager = ActivityLog.objects.filter(event_code="contract.signed_manager", deal=deal).order_by("-id").first()
    assert signed_manager.event_params == {"number": contract.number, "deal_id": deal.id, "manual": True}

    # billing.py — invoice.issued + payment.recorded (money as str, manual flag). Wave C: creation
    # emits invoice.created (DRAFT); the invoice.issued event now rides the explicit issue step.
    invoice, err = crm_services.generate_invoice_from_contract(contract.id, actor=manager)
    assert err is None
    created = ActivityLog.objects.filter(event_code="invoice.created", deal=deal).order_by("-id").first()
    assert created.event_params == {"number": invoice.number, "deal_id": deal.id}
    invoice, err = crm_services.issue_invoice(invoice, manager)
    assert err is None
    issued = ActivityLog.objects.filter(event_code="invoice.issued", deal=deal).order_by("-id").first()
    assert issued.event_params == {"number": invoice.number, "deal_id": deal.id}

    _, err = crm_services.record_payment(
        invoice.id, manager, amount=invoice.total_incl_vat, paid_at=timezone.localdate(), manual=True
    )
    assert err is None
    invoice.refresh_from_db()
    paid = ActivityLog.objects.filter(event_code="payment.recorded", deal=deal).order_by("-id").first()
    assert paid.event_params == {
        "number": invoice.number,
        "amount": str(invoice.total_incl_vat),
        "paid": str(invoice.amount_paid),
        "total": str(invoice.total_incl_vat),
        "manual": True,
    }
    # act.signed (billing.py) is the same additive shape but is unreachable to exercise here: sign_act's
    # pre-existing `select_for_update().select_related("status")` raises on PG (FOR UPDATE on a nullable
    # outer join), independent of this change — see the handoff note.


# ─── S7a: below-margin-floor justification guardrail ──────────────────────────


def _ready_priced_quote(deal, manager):
    """A properly-priced КП in READY_TO_SEND — same setup the golden path sends successfully,
    so all the OTHER send guards (routing/priced-lines) are satisfied."""
    quote = _build_quote_with_items(deal, manager)
    QuoteCalculationService.recalculate_quote(quote.id)
    quote.refresh_from_db()
    quote.status = QuoteStatus.objects.get(code="READY_TO_SEND")
    quote.save(update_fields=["status"])
    return quote


def _stage_ready_to_send(deal):
    """Park the deal in CALCULATING — the only stage send_to_client can legally advance from
    directly (RFQ_OPEN/SOURCING route through it first). The guardrail tests below assert the
    SEND, not the FSM, so the stage is set up front rather than driven through the whole path."""
    deal.stage = DealStage.objects.get(code="CALCULATING")
    deal.save(update_fields=["stage"])


# Force the margin-governance verdict deterministically — the economics engine itself is tested
# elsewhere; here we isolate the GUARDRAIL (below_floor ⇒ justification required).
_BELOW_FLOOR_ECON = {
    "total_landed_cost": Decimal("1000.00"),
    "gross_profit": Decimal("50.00"),
    "gross_margin_percent": Decimal("4.8"),
    "markup_percent": Decimal("5.0"),
    "charge_cost_total": Decimal("0.00"),
    "operating_profit": Decimal("50.00"),
    "fx_missing": False,
    "below_cost": False,
    "below_floor": True,
    "min_margin_percent": Decimal("15"),
    "target_margin_percent": Decimal("25"),
}


@pytest.mark.django_db
def test_send_below_floor_requires_justification(deal, buyer, manager):
    """Sending a КП under the company margin FLOOR without a justification is blocked with the
    specific code — the guard fires BEFORE the status change, so nothing is sent. (The happy
    send + audit event ride the golden path; here we pin the guardrail's block.)"""
    from unittest.mock import patch

    quote = _ready_priced_quote(deal, manager)

    with patch("crm.services.quotes.lifecycle.compute_quote_economics", return_value=dict(_BELOW_FLOOR_ECON)):
        with pytest.raises(ValueError, match="BELOW_FLOOR_JUSTIFICATION_REQUIRED"):
            QuoteLifecycleService.send_to_client(quote.id, manager)
    quote.refresh_from_db()
    assert quote.status.code == "READY_TO_SEND"  # not sent — the guard rejected before any state change


@pytest.mark.django_db
def test_send_below_floor_justification_too_long(deal, buyer, manager):
    """The justification is length-capped (can't be abused as a free-text dump)."""
    from unittest.mock import patch

    quote = _ready_priced_quote(deal, manager)
    with patch("crm.services.quotes.lifecycle.compute_quote_economics", return_value=dict(_BELOW_FLOOR_ECON)):
        with pytest.raises(ValueError, match="JUSTIFICATION_TOO_LONG"):
            QuoteLifecycleService.send_to_client(quote.id, manager, justification="x" * 501)


@pytest.mark.django_db
def test_send_below_floor_writes_audit_event_with_justification(deal, buyer, manager):
    """T3: a below-floor send is ALLOWED with a justification — and must leave a first-class
    `quote.sent_below_floor` ActivityLog row carrying the justification and both margin numbers.
    Without this the guardrail would be unauditable: the send goes through and nothing records
    WHY the company accepted a sub-floor margin (S7a, PR #355)."""
    from unittest.mock import patch

    from crm.models import ActivityLog

    quote = _ready_priced_quote(deal, manager)
    _stage_ready_to_send(deal)

    with patch("crm.services.quotes.lifecycle.compute_quote_economics", return_value=dict(_BELOW_FLOOR_ECON)):
        QuoteLifecycleService.send_to_client(quote.id, manager, justification="Стратегический клиент, вход в тендер")

    quote.refresh_from_db()
    assert quote.status.code == "SENT"

    event = ActivityLog.objects.get(event_code="quote.sent_below_floor", entity_type="quote", entity_id=quote.id)
    assert event.detail == "Стратегический клиент, вход в тендер"
    assert event.event_params["justification"] == "Стратегический клиент, вход в тендер"
    assert event.event_params["margin_percent"] == "4.8"
    assert event.event_params["floor_percent"] == "15"
    assert event.event_params["version"] == quote.version
    assert event.user_id == manager.id
    assert event.deal_id == deal.id


@pytest.mark.django_db
def test_above_floor_send_writes_no_below_floor_event(deal, buyer, manager):
    """The audit event is specific to the guardrail — a normal send must not emit it (otherwise
    the below-floor signal would be noise on every КП)."""
    from crm.models import ActivityLog

    quote = _ready_priced_quote(deal, manager)
    _stage_ready_to_send(deal)
    QuoteLifecycleService.send_to_client(quote.id, manager)

    assert not ActivityLog.objects.filter(event_code="quote.sent_below_floor", entity_id=quote.id).exists()


@pytest.mark.django_db
def test_send_without_any_recipient_is_blocked_before_status_change(deal, buyer, manager):
    """B5: the КП must not be marked SENT when there is nobody to send it to. The email task used
    to log `no_recipient` and return while the quote was already frozen + SENT and the deal had
    moved to QUOTE_SENT — «отправлено в никуда», with no signal to the seller. The gate is
    synchronous and fires BEFORE any state change."""
    quote = _ready_priced_quote(deal, manager)
    deal.client = None  # no registered buyer and no offline contact → unreachable
    deal.save(update_fields=["client"])

    with pytest.raises(ValueError, match="RECIPIENT_REQUIRED"):
        QuoteLifecycleService.send_to_client(quote.id, manager)

    quote.refresh_from_db()
    deal.refresh_from_db()
    assert quote.status.code == "READY_TO_SEND"
    assert quote.frozen_at is None
    assert deal.stage.code != "QUOTE_SENT"


@pytest.mark.django_db
def test_send_to_offline_contact_without_registered_client_is_allowed(deal, buyer, manager):
    """The gate mirrors the email task EXACTLY: an offline contact with an email IS a valid
    recipient (the unified-send path), so a contact-only deal must still send."""
    from accounts.models import Contact

    _buyer_user, buyer_co = buyer
    quote = _ready_priced_quote(deal, manager)
    deal.client = None
    deal.contact = Contact.objects.create(company=buyer_co, name="Оффлайн Клиент", email="offline@example.com")
    deal.save(update_fields=["client", "contact"])
    _stage_ready_to_send(deal)

    QuoteLifecycleService.send_to_client(quote.id, manager)

    quote.refresh_from_db()
    assert quote.status.code == "SENT"

"""Tests for AI match-outcome telemetry (spec-remaining-2026-07-07, AI-калибровка).

Every AI fuzzy top-candidate proposed during draft-КП generation is persisted (AIMatchOutcome),
resolved by the seller's later actions (reassign / clear / send), and swept by the
`ai_match_report` command to calibrate AI_DRAFT_MATCH_CONFIDENCE on real traffic.
"""

from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import CommandError, call_command

from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyType,
    CustomUser,
    VerificationStatus,
    WorkspaceRole,
)
from catalog.models import Product, ProductStatus, SupplierOffer
from crm.models import AIMatchOutcome, Deal, DealSellerRouting, DealStage, Quote, QuoteItem, QuoteStatus
from crm.services.ai_telemetry import finalize_outcomes_on_send
from crm.services.draft_quote import generate_draft_quote
from crm.services.quotes import reassign_quote_item_product
from master_data.models import Currency


@pytest.fixture(autouse=True)
def _disable_ai_by_default(settings):
    # Same guard as test_draft_quote.py: local dev has ANTHROPIC_API_KEY → AI on; the fuzzy tests
    # opt back in and mock the matcher so no real Claude call ever fires.
    settings.AI_IMPORT_ENABLED = False


@pytest.fixture
def scene(db):
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    usd = Currency.objects.get_or_create(code="USD", defaults={"name": "USD", "symbol": "$", "sort_order": 10})[0]
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 10})
    draft = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]

    buyer = Company.objects.create(name="Buyer", inn="1110000031")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    seller = Company.objects.create(name="Seller", inn="2220000031")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    from datetime import timedelta

    from django.utils import timezone

    from accounts.models import SupplierSubscription

    SupplierSubscription.objects.create(
        company=seller,
        plan="BASIC",
        status="ACTIVE",
        valid_from=timezone.now().date(),
        valid_until=(timezone.now() + timedelta(days=365)).date(),
    )

    deal = Deal.objects.create(title="RFQ", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller)
    # Buyer request: ONE free-text line — the AI fuzzy candidate target.
    request_quote = Quote.objects.create(deal=deal, version=1, status=draft)
    QuoteItem.objects.create(quote=request_quote, quantity=2, imported_raw_name="Тормозная колодка")

    role = CompanyRole.objects.create(company=seller, name="Менеджер", permissions=["quote.edit_pricing"])
    ws = WorkspaceRole.objects.get_or_create(code="SALES_MANAGER", defaults={"name": "SM", "sort_order": 10})[0]
    seller_user = CustomUser.objects.create_user(email="tm@s.uz", username="tm@s.uz", password="pw", is_active=True)
    CompanyMember.objects.create(
        user=seller_user, company=seller, role=ws, company_role=role, is_active=True, is_primary=True, can_sell=True
    )
    return locals()


def _published_product(scene, name="Тормозная колодка гребневая", priced=False):
    pub = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Published", "sort_order": 10})[0]
    product = Product.objects.create(name=name, status=pub)
    if priced:
        SupplierOffer.objects.create(
            product=product,
            supplier=scene["seller"],
            base_price=Decimal("15.00"),
            currency=scene["usd"],
            in_stock_lead_time_days=7,
        )
    return product


def _fake_match(product, confidence):
    def _inner(lines, domain_code=None, top_k=3):
        return [
            {
                "line_index": 0,
                "name_canonical": "",
                "candidates": [
                    {"product_id": product.id, "name": product.name, "sku": "", "confidence": confidence, "reason": "x"}
                ],
            }
        ]

    return _inner


def _draft_with_candidate(scene, settings, monkeypatch, confidence):
    product = _published_product(scene)
    settings.AI_IMPORT_ENABLED = True
    settings.AI_DRAFT_MATCH_CONFIDENCE = 0.9
    monkeypatch.setattr("sourcing.services_ai.match_lines_to_catalog", _fake_match(product, confidence))
    quote, err, _ = generate_draft_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    return quote, product


# ── recording at draft time ─────────────────────────────────────────────────


def test_draft_records_bound_outcome(scene, settings, monkeypatch):
    """An auto-bound fuzzy candidate (confidence ≥ threshold) persists a full telemetry row."""
    quote, product = _draft_with_candidate(scene, settings, monkeypatch, 0.95)
    outcome = AIMatchOutcome.objects.get()
    assert outcome.quote_id == quote.id
    assert outcome.quote_item_id == quote.items.get(imported_raw_name="Тормозная колодка").id
    assert outcome.seller_company_id == scene["seller"].id
    assert outcome.candidate_product_id == product.id
    assert outcome.confidence == Decimal("0.950")
    assert outcome.threshold_used == Decimal("0.900")
    assert outcome.auto_bound is True
    assert outcome.final_product_id == product.id  # bound → the draft line carries the candidate
    assert outcome.resolution == AIMatchOutcome.RESOLUTION_PENDING
    assert outcome.line_raw == "Тормозная колодка"


def test_draft_records_below_threshold_outcome(scene, settings, monkeypatch):
    """A below-threshold candidate is NOT bound but IS recorded — the calibration signal for
    lower thresholds."""
    quote, product = _draft_with_candidate(scene, settings, monkeypatch, 0.5)
    assert quote.items.get(imported_raw_name="Тормозная колодка").product_id is None
    outcome = AIMatchOutcome.objects.get()
    assert outcome.auto_bound is False
    assert outcome.candidate_product_id == product.id
    assert outcome.final_product_id is None
    assert outcome.resolution == AIMatchOutcome.RESOLUTION_PENDING


def test_no_outcomes_when_ai_disabled(scene):
    quote, err, _ = generate_draft_quote(scene["deal"].id, scene["seller_user"])
    assert err is None
    assert AIMatchOutcome.objects.count() == 0


# ── resolution by seller actions ────────────────────────────────────────────


def test_reassign_to_other_product_resolves_reassigned(scene, settings, monkeypatch):
    quote, _product = _draft_with_candidate(scene, settings, monkeypatch, 0.95)
    other = _published_product(scene, name="Колодка другая")
    item = quote.items.get(imported_raw_name="Тормозная колодка")
    _, err = reassign_quote_item_product(item.id, scene["seller_user"], other.id)
    assert err is None
    outcome = AIMatchOutcome.objects.get()
    assert outcome.resolution == AIMatchOutcome.RESOLUTION_REASSIGNED
    assert outcome.final_product_id == other.id
    assert outcome.resolved_at is not None


def test_reassign_clear_resolves_cleared(scene, settings, monkeypatch):
    quote, _product = _draft_with_candidate(scene, settings, monkeypatch, 0.95)
    item = quote.items.get(imported_raw_name="Тормозная колодка")
    _, err = reassign_quote_item_product(item.id, scene["seller_user"], None)
    assert err is None
    outcome = AIMatchOutcome.objects.get()
    assert outcome.resolution == AIMatchOutcome.RESOLUTION_CLEARED
    assert outcome.final_product_id is None


def test_manual_bind_of_unbound_line_resolves_manual(scene, settings, monkeypatch):
    """The seller manually binding a line the AI left unbound is the 'AI was right but shy'
    signal when the picked product equals the candidate."""
    quote, product = _draft_with_candidate(scene, settings, monkeypatch, 0.5)
    item = quote.items.get(imported_raw_name="Тормозная колодка")
    _, err = reassign_quote_item_product(item.id, scene["seller_user"], product.id)
    assert err is None
    outcome = AIMatchOutcome.objects.get()
    assert outcome.resolution == AIMatchOutcome.RESOLUTION_MANUAL_BOUND
    assert outcome.final_product_id == product.id  # == candidate → correct for the report


# ── finalization on send ────────────────────────────────────────────────────


def test_finalize_on_send_snapshots_pending_rows(scene, settings, monkeypatch):
    quote, product = _draft_with_candidate(scene, settings, monkeypatch, 0.95)
    finalize_outcomes_on_send(quote)
    outcome = AIMatchOutcome.objects.get()
    assert outcome.resolution == AIMatchOutcome.RESOLUTION_SENT
    assert outcome.final_product_id == product.id
    assert outcome.resolved_at is not None


def test_finalize_on_send_deleted_line_becomes_cleared(scene, settings, monkeypatch):
    quote, _product = _draft_with_candidate(scene, settings, monkeypatch, 0.95)
    quote.items.get(imported_raw_name="Тормозная колодка").delete()
    finalize_outcomes_on_send(quote)
    outcome = AIMatchOutcome.objects.get()
    assert outcome.quote_item_id is None
    assert outcome.resolution == AIMatchOutcome.RESOLUTION_CLEARED
    assert outcome.final_product_id is None


def test_finalize_keeps_explicit_verdict_but_resnapshots_truth(scene, settings, monkeypatch):
    """A reassign verdict survives send; final_product is re-snapshotted from the sent line."""
    quote, _product = _draft_with_candidate(scene, settings, monkeypatch, 0.95)
    other = _published_product(scene, name="Колодка другая")
    item = quote.items.get(imported_raw_name="Тормозная колодка")
    reassign_quote_item_product(item.id, scene["seller_user"], other.id)
    finalize_outcomes_on_send(quote)
    outcome = AIMatchOutcome.objects.get()
    assert outcome.resolution == AIMatchOutcome.RESOLUTION_REASSIGNED
    assert outcome.final_product_id == other.id


# ── report command ──────────────────────────────────────────────────────────


def test_ai_match_report_sweeps_thresholds(scene, settings, monkeypatch):
    quote, product = _draft_with_candidate(scene, settings, monkeypatch, 0.95)
    finalize_outcomes_on_send(quote)  # → SENT, correct at any threshold ≤ 0.95
    AIMatchOutcome.objects.create(  # a resolved MISS at 0.8 confidence (candidate rejected)
        quote=quote,
        seller_company=scene["seller"],
        line_raw="Гайка М12",
        candidate_product=product,
        confidence=Decimal("0.800"),
        threshold_used=Decimal("0.900"),
        auto_bound=False,
        resolution=AIMatchOutcome.RESOLUTION_CLEARED,
        final_product=None,
    )
    out = StringIO()
    call_command("ai_match_report", stdout=out)
    text = out.getvalue()
    assert "Resolved outcomes: 2" in text
    assert "1/2" in text  # top candidate correct overall
    # At 0.7 both rows would bind → precision 50%; at 0.9 only the correct one → 100%.
    assert "0.70 |          2 |     50.0%" in text
    assert "0.90 |          1 |    100.0%" in text


def test_ai_match_report_excludes_pending_and_scopes_company(scene, settings, monkeypatch):
    _quote, _product = _draft_with_candidate(scene, settings, monkeypatch, 0.95)  # stays PENDING
    out = StringIO()
    call_command("ai_match_report", "--company", str(scene["seller"].id), stdout=out)
    assert "Resolved outcomes: 0 (pending, excluded: 1)" in out.getvalue()


def test_ai_match_report_rejects_bad_thresholds(db):
    with pytest.raises(CommandError):
        call_command("ai_match_report", "--thresholds", "abc")
    with pytest.raises(CommandError):
        call_command("ai_match_report", "--thresholds", "1.5")

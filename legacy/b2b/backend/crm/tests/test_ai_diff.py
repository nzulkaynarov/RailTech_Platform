"""AI #3 «КП vs заявка» coverage/diff — deterministic detection + id-scope guard.

The Claude client is stubbed (no paid / nondeterministic calls); we assert the
deterministic contract:
  * uncovered (unpriced, unmatched) request lines are detected in PURE CODE, even
    when AI is OFF (the feature degrades, never disappears),
  * the AI semantic layer only ADDS findings on the lines it is given and an
    invented out-of-range index is dropped (Rule 1),
  * the per-quote visibility guard (`user_can_view_quote_diff`) admits the deal's
    buyer and a routed seller, and refuses a stranger,
  * the endpoint is scoped: a stranger gets 403, never another tenant's data.
"""

from decimal import Decimal
from types import SimpleNamespace

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteItem, QuoteStatus
from master_data.models import Currency


def _stub_response(findings):
    text = __import__("json").dumps({"findings": findings})
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=1, output_tokens=1),
    )


def _seed_lookups():
    DealStage.objects.get_or_create(code="SOURCING", defaults={"name": "Sourcing", "sort_order": 30})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    Currency.objects.get_or_create(code="USD", defaults={"name": "US Dollar", "symbol": "$", "sort_order": 10})


def _make_world():
    """A buyer-owned deal + routed seller, and a КП with three lines:
      0) uncovered  — no product, zero price (seller never priced it),
      1) substituted — a catalog product whose name differs from the request,
      2) covered     — priced with a matching name (clean).
    Returns (buyer, seller, stranger, quote).
    """
    _seed_lookups()
    usd = Currency.objects.get(code="USD")

    buyer = CustomUser.objects.create_user(
        email="aidiff-buyer@x.test", username="aidiff-buyer@x.test", password="pw", is_active=True
    )
    buyer_co = Company.objects.create(name="Diff Buyer Co", inn="710710710")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    CompanyMember.objects.create(
        user=buyer, company=buyer_co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True
    )

    seller = CustomUser.objects.create_user(
        email="aidiff-seller@x.test", username="aidiff-seller@x.test", password="pw", is_active=True
    )
    seller_co = Company.objects.create(name="Diff Seller Co", inn="810810810")
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    CompanyMember.objects.create(
        user=seller,
        company=seller_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        can_sell=True,
    )

    stranger = CustomUser.objects.create_user(
        email="aidiff-stranger@x.test", username="aidiff-stranger@x.test", password="pw", is_active=True
    )

    deal = Deal.objects.create(
        title="Diff Deal",
        company=buyer_co,
        client=buyer,
        stage=DealStage.objects.get(code="SOURCING"),
    )
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)

    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )

    def _add_item(**fields):
        # skip_recalculate is a save() kwarg (the model pops it) — not a field, so it
        # cannot be passed to objects.create(). Build then save to avoid per-item
        # quote recalculation churn.
        item = QuoteItem(quote=quote, **fields)
        item.save(skip_recalculate=True)
        return item

    # Line 0 — uncovered: requested by name, no product, zero price.
    _add_item(
        imported_raw_name="Тормозная колодка ГОСТ 1205",
        quantity=10,
        unit="шт.",
        frozen_base_price=Decimal("0"),
        final_price_excl_vat=Decimal("0"),
    )
    # Line 1 — substituted: priced with a DIFFERENT-named catalog product.
    substitute = Product.objects.create(name="Колодка тормозная аналог XYZ")
    _add_item(
        imported_raw_name="Тормозная колодка ГОСТ 1205",
        product=substitute,
        quantity=5,
        unit="шт.",
        frozen_base_price=Decimal("100"),
        frozen_currency=usd,
        margin_percent=Decimal("10"),
        final_price_excl_vat=Decimal("110"),
        note="Только оригинал, замена не допускается",
    )
    # Line 2 — covered cleanly.
    matched = Product.objects.create(name="Болт М12")
    _add_item(
        imported_raw_name="Болт М12",
        product=matched,
        quantity=100,
        unit="шт.",
        frozen_base_price=Decimal("1"),
        frozen_currency=usd,
        margin_percent=Decimal("5"),
        final_price_excl_vat=Decimal("1.05"),
    )
    return buyer, seller, stranger, quote


@pytest.mark.django_db
def test_uncovered_line_detected_with_ai_off(settings):
    """AI OFF → deterministic findings still flag the uncovered line. No paid call."""
    settings.AI_IMPORT_ENABLED = False
    from crm.services import quote_vs_request_diff

    _buyer, _seller, _stranger, quote = _make_world()
    result = quote_vs_request_diff(quote)

    assert result["ai_enabled"] is False
    uncovered = [f for f in result["findings"] if f["issue_type"] == "uncovered"]
    assert len(uncovered) == 1
    assert uncovered[0]["line"] == 0
    # With AI off there must be NO semantic (substituted / note_ignored) findings.
    assert all(f["issue_type"] == "uncovered" for f in result["findings"])


@pytest.mark.django_db
def test_ai_layer_adds_semantic_findings_and_drops_bad_index(settings, monkeypatch):
    """AI ON → deterministic uncovered finding PLUS the model's semantic verdicts,
    while an out-of-range index the model invents is dropped (Rule 1)."""
    settings.AI_IMPORT_ENABLED = True
    fake = _stub_response(
        [
            {"line": 1, "issue_type": "note_ignored", "explanation": "Замена не допускалась, а предложен аналог."},
            {"line": 99, "issue_type": "substituted", "explanation": "Несуществующая строка — должна быть отброшена."},
        ]
    )
    monkeypatch.setattr(
        "crm.services.ai_diff._client",
        lambda: SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: fake)),
    )
    from crm.services import quote_vs_request_diff

    _buyer, _seller, _stranger, quote = _make_world()
    result = quote_vs_request_diff(quote)

    assert result["ai_enabled"] is True
    issue_types = {(f["line"], f["issue_type"]) for f in result["findings"]}
    assert (0, "uncovered") in issue_types  # deterministic
    assert (1, "note_ignored") in issue_types  # semantic, valid line
    # The invented index 99 must NOT appear.
    assert all(f["line"] != 99 for f in result["findings"])


@pytest.mark.django_db
def test_visibility_guard(settings):
    """Buyer + routed seller may view; a stranger may not."""
    settings.AI_IMPORT_ENABLED = False
    from crm.services import user_can_view_quote_diff

    buyer, seller, stranger, quote = _make_world()
    assert user_can_view_quote_diff(buyer, quote) is True
    assert user_can_view_quote_diff(seller, quote) is True
    assert user_can_view_quote_diff(stranger, quote) is False


@pytest.mark.django_db
def test_endpoint_scope_stranger_403(settings):
    """Endpoint contract: a stranger gets 403 (never another tenant's data). The
    route is wired in core/urls.py (shared file owned by the orchestrator); skip if
    not yet registered in this checkout rather than fail the standalone run."""
    from django.urls import NoReverseMatch, reverse
    from rest_framework.test import APIClient

    settings.AI_IMPORT_ENABLED = False
    _buyer, _seller, stranger, quote = _make_world()
    try:
        url = reverse("quote-request-diff", kwargs={"quote_id": quote.id})
    except NoReverseMatch:
        pytest.skip("quote-request-diff route not wired yet (orchestrator registers it in core/urls.py)")

    client = APIClient()
    client.force_authenticate(stranger)
    response = client.get(url)
    assert response.status_code == 403


@pytest.mark.django_db
def test_endpoint_buyer_ok(settings):
    """The deal's buyer gets a 200 with deterministic findings even with AI off."""
    from django.urls import NoReverseMatch, reverse
    from rest_framework.test import APIClient

    settings.AI_IMPORT_ENABLED = False
    buyer, _seller, _stranger, quote = _make_world()
    try:
        url = reverse("quote-request-diff", kwargs={"quote_id": quote.id})
    except NoReverseMatch:
        pytest.skip("quote-request-diff route not wired yet (orchestrator registers it in core/urls.py)")

    client = APIClient()
    client.force_authenticate(buyer)
    response = client.get(url)
    assert response.status_code == 200
    assert any(f["issue_type"] == "uncovered" for f in response.data["findings"])

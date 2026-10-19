"""`GET /crm/contracts/?deal=<id>` must actually filter (F1).

PR #465 gave Invoice / Act / Payment / Fulfillment an explicit FilterSet because
``DjangoFilterBackend`` without ``filterset_fields``/``filterset_class`` returns the
queryset UNCHANGED — silently, with no 400. ``ContractViewSet`` was left out.

That is not cosmetic: ``BuyerAcceptedPanel`` calls ``useContracts({ deal })`` and then
takes the newest non-CANCELLED row of whatever comes back. With the filter ignored, a
buyer who owns two deals sees deal B's contract number on deal A's card — and the
«Перейти к договору» deep-link opens the WRONG contract.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Contract, ContractStatus, Deal, DealStage, Quote, QuoteStatus

CONTRACTS_URL = "/api/v1/crm/contracts/"


@pytest.fixture
def lookups(db):
    """Seed the codes this flow asserts on (--nomigrations skips the data migrations)."""
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    DealStage.objects.get_or_create(code="CONTRACT_SIGNED", defaults={"name": "Signed", "sort_order": 70})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    ContractStatus.objects.get_or_create(code="PENDING_CLIENT", defaults={"name": "Pending", "sort_order": 20})
    ContractStatus.objects.get_or_create(code="CANCELLED", defaults={"name": "Cancelled", "sort_order": 90})


@pytest.fixture
def two_deals_one_buyer(lookups):
    """ONE buyer company owning TWO deals, each with its own contract."""
    buyer_co = Company.objects.create(name="Buyer Co", inn="B900")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    buyer_user = CustomUser.objects.create_user(
        email="buyer@twodeals.test", username="buyer@twodeals.test", password="x"
    )
    CompanyMember.objects.create(
        user=buyer_user,
        company=buyer_co,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
    )

    stage = DealStage.objects.get(code="CONTRACT_SIGNED")
    draft = QuoteStatus.objects.get(code="DRAFT")
    pending = ContractStatus.objects.get(code="PENDING_CLIENT")

    made = {}
    for key, number in (("first", "CT-FILTER-001"), ("second", "CT-FILTER-002")):
        deal = Deal.objects.create(title=f"Deal {key}", company=buyer_co, stage=stage)
        quote = Quote.objects.create(
            deal=deal,
            version=1,
            status=draft,
            subtotal_excl_vat=Decimal("100"),
            vat_amount=Decimal("12"),
            total_incl_vat=Decimal("112"),
        )
        contract = Contract.objects.create(
            deal=deal, quote=quote, number=number, status=pending, total_amount=Decimal("112")
        )
        made[key] = {"deal": deal, "contract": contract}
    return {"user": buyer_user, **made}


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _rows(resp):
    data = resp.json()
    return data["results"] if isinstance(data, dict) and "results" in data else data


def test_contracts_filter_by_deal_returns_only_that_deals_contract(two_deals_one_buyer):
    """The bug: ?deal=<id> was ignored, so BOTH contracts came back and the panel showed
    whichever sorted first — i.e. the other deal's contract."""
    first = two_deals_one_buyer["first"]
    resp = _api(two_deals_one_buyer["user"]).get(CONTRACTS_URL, {"deal": first["deal"].id})

    assert resp.status_code == 200
    returned = {row["id"] for row in _rows(resp)}
    assert returned == {first["contract"].id}, "?deal= must not leak the other deal's contract"


def test_contracts_filter_by_deal_is_not_a_no_op(two_deals_one_buyer):
    """Guard against a filter that 'passes' only because the fixture has one row: the
    unfiltered list must contain BOTH contracts, the filtered one exactly half."""
    client = _api(two_deals_one_buyer["user"])
    unfiltered = {row["id"] for row in _rows(client.get(CONTRACTS_URL))}
    assert len(unfiltered) == 2, "fixture must expose two contracts for this guard to mean anything"

    second = two_deals_one_buyer["second"]
    filtered = {row["id"] for row in _rows(client.get(CONTRACTS_URL, {"deal": second["deal"].id}))}
    assert filtered == {second["contract"].id}


def test_contracts_filter_by_status_code(two_deals_one_buyer):
    """`?status=` takes the CODE (the SPA compares codes, Rule 2), and accepts a list."""
    second = two_deals_one_buyer["second"]
    second["contract"].status = ContractStatus.objects.get(code="CANCELLED")
    second["contract"].save(update_fields=["status"])

    client = _api(two_deals_one_buyer["user"])
    live = {row["id"] for row in _rows(client.get(CONTRACTS_URL, {"status": "PENDING_CLIENT"}))}
    assert live == {two_deals_one_buyer["first"]["contract"].id}

    both = {row["id"] for row in _rows(client.get(CONTRACTS_URL, {"status": "PENDING_CLIENT,CANCELLED"}))}
    assert both == {two_deals_one_buyer["first"]["contract"].id, second["contract"].id}

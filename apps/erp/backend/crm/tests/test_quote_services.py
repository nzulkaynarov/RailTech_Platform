"""
Service-level tests for high-risk CRM logic (CLAUDE.md "Known test debt"):
force_approve_quote and reject_quote — the override paths that previously had no
direct coverage.
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Deal, DealStage, Quote, QuoteStatus
from crm.services.quotes import QuoteLifecycleService
from master_data.models import Country


@pytest.fixture
def lookups(db):
    for code in ["DRAFT", "CALCULATING", "QUOTE_SENT", "CONTRACT_SIGNED", "CLOSED_LOST"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "SENT", "APPROVED", "REJECTED"]:
        QuoteStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    Country.objects.get_or_create(code="UZ", defaults={"name": "Uzbekistan", "sort_order": 10})
    from notifications.models import NotificationType

    for code in ["INFO", "SUCCESS", "WARNING", "ERROR"]:
        NotificationType.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


@pytest.fixture
def buyer(lookups):
    user = CustomUser.objects.create_user(
        email="q.buyer@example.com", username="q_buyer", password="pw", is_active=True
    )
    company = Company.objects.create(name="Q Buyer LLC", inn="9900000001")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_primary=True, is_active=True
    )
    return user, company


@pytest.fixture
def admin_user(lookups):
    return CustomUser.objects.create_user(
        email="q.admin@example.com",
        username="q_admin",
        password="pw",
        is_active=True,
        is_staff=True,
        is_superuser=True,
        role=SystemRole.objects.get(code="USER"),
    )


@pytest.fixture
def deal(buyer, admin_user):
    buyer_user, buyer_co = buyer
    return Deal.objects.create(
        title="Q Deal",
        company=buyer_co,
        client=buyer_user,
        manager=admin_user,
        stage=DealStage.objects.get(code="DRAFT"),
    )


def _quote(deal, status_code):
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code=status_code),
        tax_country=Country.objects.get(code="UZ"),
        vat_rate=Decimal("12.00"),
        subtotal_excl_vat=Decimal("100.00"),
        vat_amount=Decimal("12.00"),
        total_incl_vat=Decimal("112.00"),
    )


# ─── force_approve_quote ────────────────────────────────────────────────────


@pytest.mark.django_db
def test_force_approve_requires_platform_admin(deal, buyer):
    buyer_user, _ = buyer
    quote = _quote(deal, "DRAFT")
    result, err = QuoteLifecycleService.force_approve_quote(quote.id, buyer_user, reason="x")
    assert result is None
    assert err == "PLATFORM_ADMIN_REQUIRED"


@pytest.mark.django_db
def test_force_approve_requires_reason(deal, admin_user):
    quote = _quote(deal, "DRAFT")
    result, err = QuoteLifecycleService.force_approve_quote(quote.id, admin_user, reason="")
    assert result is None
    assert err == "FORCE_REASON_REQUIRED"


@pytest.mark.django_db
def test_force_approve_succeeds_for_admin_with_reason(deal, admin_user):
    quote = _quote(deal, "DRAFT")
    result, err = QuoteLifecycleService.force_approve_quote(quote.id, admin_user, reason="client approved by phone")
    assert err is None
    assert result.status.code == "APPROVED"


# ─── reject_quote ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_reject_quote_only_when_sent(deal, buyer):
    buyer_user, _ = buyer
    quote = _quote(deal, "DRAFT")
    with pytest.raises(ValueError):
        QuoteLifecycleService.reject_quote(quote.id, buyer_user, reason="too expensive")


@pytest.mark.django_db
def test_reject_quote_moves_deal_back_to_calculating(deal, buyer):
    buyer_user, _ = buyer
    deal.stage = DealStage.objects.get(code="QUOTE_SENT")
    deal.save(update_fields=["stage"])
    quote = _quote(deal, "SENT")
    result = QuoteLifecycleService.reject_quote(quote.id, buyer_user, reason="too expensive")
    assert result.status.code == "REJECTED"
    deal.refresh_from_db()
    assert deal.stage.code == "CALCULATING"

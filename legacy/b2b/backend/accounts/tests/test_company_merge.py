"""Tests for company identity merge + CB-auto-populate (CRM Phase C).

A seller's offline placeholder Company (is_registered=False, stated_inn) is folded into the real
registered survivor once its identity is known — re-parenting contacts / deals / activity /
relationship edges. Merge is admin-only and one-directional (only an offline source). On KYC verify
the fold happens automatically for INN-matching placeholders (auto-populate).
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, Contact, CustomUser, VerificationStatus, WorkspaceRole
from accounts.services.merge import auto_populate_history, find_offline_duplicates, merge_companies
from crm.models import ActivityLog, CounterpartyRelationship, Deal, DealSellerRouting, DealStage, RelationshipDirection
from crm.services.relationships import touch_relationship


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    for code, order in (("L1_UNVERIFIED", 0), ("L2_VERIFIED", 20)):
        VerificationStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": order})


def _seller(lookups):
    company = Company.objects.create(name="Seller Co", inn="S100")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(
        email="pc-seller@t.test", username="pc-seller@t.test", password="x", is_active=True
    )
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user, company


def _offline_placeholder(name="Оффлайн Буер", stated_inn="B999"):
    company = Company.objects.create(name=name, stated_inn=stated_inn, is_registered=False)
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    return company


# ── duplicate discovery ─────────────────────────────────────────────────────


def test_find_offline_duplicates_matches_stated_inn(lookups):
    survivor = Company.objects.create(name="Real Buyer", inn="B999", is_registered=True)
    dup = _offline_placeholder(stated_inn="B999")
    _offline_placeholder(name="Unrelated", stated_inn="B111")  # different INN → not a match
    found = list(find_offline_duplicates(survivor))
    assert found == [dup]


def test_find_offline_duplicates_empty_without_inn(lookups):
    survivor = Company.objects.create(name="No INN", inn="", is_registered=True)
    _offline_placeholder(stated_inn="")
    assert list(find_offline_duplicates(survivor)) == []


# ── merge mechanics ─────────────────────────────────────────────────────────


def test_merge_reparents_contacts_deals_activity(lookups):
    seller_user, seller_co = _seller(lookups)
    survivor = Company.objects.create(name="Real Buyer", inn="B999", is_registered=True)
    dup = _offline_placeholder(stated_inn="B999")

    Contact.objects.create(company=dup, name="Иван", email="ivan@buyer.test", is_primary=True)
    deal = Deal.objects.create(title="Old deal", company=dup, stage=DealStage.objects.get(code="DRAFT"))
    ActivityLog.objects.create(action="Событие", company=dup, deal=deal)

    result, err = merge_companies(survivor, dup, actor=seller_user)
    assert err is None and result.id == survivor.id
    assert not Company.objects.filter(pk=dup.pk).exists()  # duplicate gone
    assert survivor.contacts.filter(email="ivan@buyer.test").exists()
    assert Deal.objects.get(pk=deal.pk).company_id == survivor.id
    assert ActivityLog.objects.filter(action="Событие", company=survivor).exists()


def test_merge_refuses_registered_source(lookups):
    survivor = Company.objects.create(name="Survivor", inn="B999", is_registered=True)
    registered_dup = Company.objects.create(name="Also Registered", inn="B998", is_registered=True)
    result, err = merge_companies(survivor, registered_dup)
    assert result is None and err == "MERGE_SOURCE_REGISTERED"


def test_merge_refuses_source_with_account(lookups):
    survivor = Company.objects.create(name="Survivor", inn="B999", is_registered=True)
    dup = _offline_placeholder(stated_inn="B999")
    # A placeholder that somehow has a member is a real account — must not be silently moved.
    user = CustomUser.objects.create_user(email="stray@t.test", username="stray@t.test", password="x")
    CompanyMember.objects.create(user=user, company=dup, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True)
    result, err = merge_companies(survivor, dup)
    assert result is None and err == "MERGE_SOURCE_HAS_ACCOUNT"


def test_merge_refuses_same_company(lookups):
    survivor = Company.objects.create(name="X", inn="B999", is_registered=True)
    assert merge_companies(survivor, survivor) == (None, "MERGE_SAME_COMPANY")


def test_merge_dedups_relationship_edges(lookups):
    """Seller had an edge to the offline placeholder AND (after routing) to the real buyer —
    after merge the seller has ONE edge to the survivor, not a UniqueConstraint violation."""
    seller_user, seller_co = _seller(lookups)
    survivor = Company.objects.create(name="Real Buyer", inn="B999", is_registered=True)
    dup = _offline_placeholder(stated_inn="B999")

    # Seller's edge to the offline placeholder (older) and to the real buyer (newer).
    touch_relationship(
        owner_company_id=seller_co.id, counterparty_company_id=dup.id, direction=RelationshipDirection.CLIENT
    )
    touch_relationship(
        owner_company_id=seller_co.id, counterparty_company_id=survivor.id, direction=RelationshipDirection.CLIENT
    )

    result, err = merge_companies(survivor, dup, actor=seller_user)
    assert err is None
    edges = CounterpartyRelationship.objects.filter(owner_company=seller_co, direction=RelationshipDirection.CLIENT)
    assert edges.count() == 1
    assert edges.first().counterparty_company_id == survivor.id


def test_merge_recomputes_rollups_from_moved_deals(lookups):
    from crm.models import Quote, QuoteStatus

    QuoteStatus.objects.get_or_create(code="APPROVED", defaults={"name": "Approved", "sort_order": 50})
    DealStage.objects.get_or_create(code="CLOSED_WON", defaults={"name": "Won", "sort_order": 90})
    seller_user, seller_co = _seller(lookups)
    survivor = Company.objects.create(name="Real Buyer", inn="B999", is_registered=True)
    dup = _offline_placeholder(stated_inn="B999")

    # A won deal on the offline placeholder, routed to the seller.
    deal = Deal.objects.create(title="Won", company=dup, stage=DealStage.objects.get(code="CLOSED_WON"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_co)
    Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="APPROVED"),
        seller_company=seller_co,
        total_incl_vat=Decimal("2000.00"),
    )
    touch_relationship(
        owner_company_id=seller_co.id, counterparty_company_id=dup.id, direction=RelationshipDirection.CLIENT
    )

    merge_companies(survivor, dup, actor=seller_user)
    edge = CounterpartyRelationship.objects.get(owner_company=seller_co, counterparty_company=survivor)
    assert edge.deals_count == 1 and edge.won_count == 1 and edge.gmv == Decimal("2000.00")


# ── auto-populate on KYC verify ─────────────────────────────────────────────


def test_auto_populate_folds_matching_placeholders(lookups):
    seller_user, seller_co = _seller(lookups)
    survivor = Company.objects.create(name="Real Buyer", inn="B999", is_registered=True)
    dup = _offline_placeholder(stated_inn="B999")
    Contact.objects.create(company=dup, name="Иван", email="ivan@buyer.test")
    merged = auto_populate_history(survivor)
    assert merged == 1
    assert not Company.objects.filter(pk=dup.pk).exists()
    assert survivor.contacts.filter(email="ivan@buyer.test").exists()


def test_verify_kyc_triggers_auto_populate(lookups):
    from accounts.services.kyc import verify_company_kyc

    admin = CustomUser.objects.create_user(
        email="pc-admin@t.test", username="pc-admin@t.test", password="x", is_staff=True
    )
    survivor = Company.objects.create(name="Real Buyer", inn="B999", is_registered=True)
    dup = _offline_placeholder(stated_inn="B999")
    Deal.objects.create(title="Old", company=dup, stage=DealStage.objects.get(code="DRAFT"))

    # Обоснование обязательно: у компании нет KYC-документов, а политика владельца требует
    # объяснить выдачу уровня без доказательств (тест не про гейт, а про склейку истории).
    result, err = verify_company_kyc(
        survivor, admin, level_code="L2_VERIFIED", require_documents=False, reason="сверено по реестру"
    )
    assert err is None
    assert not Company.objects.filter(pk=dup.pk).exists()
    assert Deal.objects.filter(company=survivor, title="Old").exists()


# ── admin endpoint ──────────────────────────────────────────────────────────


def _admin_api(lookups):
    admin = CustomUser.objects.create_user(
        email="pc-op@t.test", username="pc-op@t.test", password="x", is_active=True, is_staff=True, is_superuser=True
    )
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(admin).access_token}")
    return client


def test_merge_endpoint_admin_only_and_works(lookups):
    survivor = Company.objects.create(name="Real Buyer", inn="B999", is_registered=True)
    dup = _offline_placeholder(stated_inn="B999")

    # A non-admin member cannot reach the merge action.
    seller_user, _ = _seller(lookups)
    member_client = APIClient()
    member_client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(seller_user).access_token}")
    resp = member_client.post(
        f"/api/v1/accounts/companies/{survivor.id}/merge/", {"duplicate_id": dup.id}, format="json"
    )
    assert resp.status_code in (403, 404)
    assert Company.objects.filter(pk=dup.pk).exists()  # untouched

    api = _admin_api(lookups)
    cand = api.get(f"/api/v1/accounts/companies/{survivor.id}/merge-candidates/")
    assert cand.status_code == 200 and any(row["id"] == dup.id for row in cand.json())

    resp = api.post(f"/api/v1/accounts/companies/{survivor.id}/merge/", {"duplicate_id": dup.id}, format="json")
    assert resp.status_code == 200 and resp.json()["merged"] is True
    assert not Company.objects.filter(pk=dup.pk).exists()

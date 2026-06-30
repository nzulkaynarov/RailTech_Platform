"""Regression tests for the 2026-06-30 post-merge adversarial-audit fixes (Move 2 / U2).

Covers:
  #2  claim_deal is a true no-op when the actor already owns the deal (assigned_at SLA anchor kept)
  #7  release_deal / assign_deal are scoped to the actor's OWN routed seller company — a co-routed
      competitor seller's admin can neither release nor seize another seller's claim (tenant isolation)
  #4  assigned_to_name is redacted across tenants (competitor seller / non-member viewer gets None)
  #5  notify_new_message alerts the claimed deal owner (assigned_to), not only client+manager
"""

from types import SimpleNamespace

import pytest

from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import Deal, DealSellerRouting, DealStage, Message
from crm.serializers import DealListSerializer
from crm.services.assignment import assign_deal, claim_deal, release_deal


# ─── helpers ────────────────────────────────────────────────────────────────


def _ws(code):
    role, _ = WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    return role


def _user(email):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)


def _member(user, company, *, company_role=None, can_sell=True, can_buy=False):
    return CompanyMember.objects.create(
        user=user, company=company, role=_ws("MEMBER"), company_role=company_role,
        is_active=True, can_sell=can_sell, can_buy=can_buy,
    )


def _team_manager_role(company):
    return CompanyRole.objects.create(company=company, name="Админ", permissions=["team.manage", "settings.edit"])


@pytest.fixture
def lookups(db):
    for code in ["DRAFT", "RFQ_OPEN", "CALCULATING"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    from notifications.models import NotificationType

    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 10})


def _company(name, inn, type_code):
    c = Company.objects.create(
        name=name, inn=inn, verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    c.types.add(CompanyType.objects.get(code=type_code))
    return c


@pytest.fixture
def scenario(lookups):
    """A buyer RFQ routed to TWO competing seller companies A and B."""
    buyer = _company("Buyer Co", "1110000001", "CLIENT")
    seller_a = _company("Seller A", "2220000001", "SUPPLIER")
    seller_b = _company("Seller B", "2220000002", "SUPPLIER")
    deal = Deal.objects.create(title="RFQ", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_a)
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_b)

    a_member = _user("a.member@a.uz")
    _member(a_member, seller_a)
    a_admin = _user("a.admin@a.uz")
    _member(a_admin, seller_a, company_role=_team_manager_role(seller_a))
    b_member = _user("b.member@b.uz")
    _member(b_member, seller_b)
    b_admin = _user("b.admin@b.uz")
    _member(b_admin, seller_b, company_role=_team_manager_role(seller_b))
    buyer_user = _user("buyer@buyer.uz")
    _member(buyer_user, buyer, can_sell=False, can_buy=True)

    return SimpleNamespace(
        deal=deal, buyer=buyer, seller_a=seller_a, seller_b=seller_b,
        a_member=a_member, a_admin=a_admin, b_member=b_member, b_admin=b_admin, buyer_user=buyer_user,
    )


# ─── #2 idempotent re-claim ─────────────────────────────────────────────────


def test_reclaim_by_owner_is_noop_and_preserves_assigned_at(scenario):
    deal, err = claim_deal(scenario.deal.id, scenario.a_member)
    assert err is None
    first_ts = deal.assigned_at
    assert first_ts is not None

    deal2, err2 = claim_deal(scenario.deal.id, scenario.a_member)
    assert err2 is None
    assert deal2.assigned_at == first_ts  # SLA anchor must NOT be reset by a repeat claim


# ─── #7 cross-seller release isolation ──────────────────────────────────────


def test_competitor_admin_cannot_release_another_sellers_claim(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)  # seller A owns it
    _, err = release_deal(scenario.deal.id, scenario.b_admin)  # seller B's admin tries to yank it
    assert err == "MEMBER_REQUIRED_FOR_ACTION"
    scenario.deal.refresh_from_db()
    assert scenario.deal.assigned_to_id == scenario.a_member.id  # still owned by A


def test_owner_can_release_own_claim(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)
    deal, err = release_deal(scenario.deal.id, scenario.a_member)
    assert err is None and deal.assigned_to_id is None


def test_own_company_admin_can_release_member_claim(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)
    deal, err = release_deal(scenario.deal.id, scenario.a_admin)  # A's own admin
    assert err is None and deal.assigned_to_id is None


# ─── #7 cross-seller assign isolation ───────────────────────────────────────


def test_competitor_admin_cannot_assign_to_their_own_member_on_anothers_claim(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)  # A owns it
    _, err = assign_deal(scenario.deal.id, scenario.b_admin, scenario.b_member.id)
    assert err == "DEAL_ALREADY_CLAIMED"  # must not overwrite a competitor's claim
    scenario.deal.refresh_from_db()
    assert scenario.deal.assigned_to_id == scenario.a_member.id


def test_competitor_admin_cannot_assign_a_rivals_member(scenario):
    _, err = assign_deal(scenario.deal.id, scenario.b_admin, scenario.a_member.id)
    assert err == "ASSIGNEE_NOT_IN_ROUTED_COMPANY"  # assignee must be in the actor's own company


def test_admin_can_assign_within_own_company(scenario):
    deal, err = assign_deal(scenario.deal.id, scenario.a_admin, scenario.a_member.id)
    assert err is None and deal.assigned_to_id == scenario.a_member.id


# ─── #4 assigned_to_name cross-tenant redaction ─────────────────────────────


def _name_as_seen_by(deal, viewer):
    ser = DealListSerializer(deal, context={"request": SimpleNamespace(user=viewer)})
    return ser.data["assigned_to_name"]


def test_assigned_to_name_redacted_from_competitor_and_buyer(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)
    deal = Deal.objects.get(pk=scenario.deal.id)
    # invited member has blank name → display falls back to email for authorized viewers
    assert _name_as_seen_by(deal, scenario.a_member) == scenario.a_member.email  # self
    assert _name_as_seen_by(deal, scenario.a_admin) == scenario.a_member.email   # same company
    assert _name_as_seen_by(deal, scenario.b_admin) is None   # competitor seller — redacted
    assert _name_as_seen_by(deal, scenario.buyer_user) is None  # buyer — redacted


# ─── #5 chat notification reaches the claimed owner ─────────────────────────


def test_new_message_notifies_claimed_owner(scenario):
    from notifications.models import Notification

    claim_deal(scenario.deal.id, scenario.a_member)  # a_member owns the deal (manager stays NULL)
    Message.objects.create(deal=scenario.deal, sender=scenario.buyer_user, text="Когда КП?", message_type="CHAT")
    assert Notification.objects.filter(user=scenario.a_member, deal=scenario.deal).exists()

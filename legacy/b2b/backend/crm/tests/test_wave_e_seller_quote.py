"""Wave E (F1–F4) — the seller-initiated КП path: offline client, calculator draft, promote.

F1  the keystone: a deal a seller opens for an offline contact gets a DealSellerRouting row,
    so it is visible to (and claimable / buildable by) its own creator. Before the fix seller
    visibility was routing-only and the creator could not see their own deal.
F3  `Deal.company` is NULLABLE — the «калькулятор» draft. The whole security story is that
    scoping stays FAIL-CLOSED: buyer-side scopes are `company_id__in=[...]`, which a NULL
    never matches, and seller-side access is the routing row — so nothing is reachable "by
    accident". The cross-tenant negatives below are the load-bearing tests.
F4  accepting a promote-invite backfills `deal.client` on the contact's historical deals.
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from accounts.services import create_offline_client
from crm.models import Deal, DealSellerRouting, DealStage, Quote, QuoteStatus

SELLER_HEADERS = {"HTTP_X_ACTIVE_CONTEXT": "SELLER"}


@pytest.fixture
def lookups(db):
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="PROFILE_SUBMITTED", defaults={"name": "Sub", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="READY_TO_SEND", defaults={"name": "Готово", "sort_order": 40})


def _seller(email, inn):
    """A seller-team user: OWNER of a SUPPLIER company, can_sell."""
    company = Company.objects.create(name=f"Seller {inn}", inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user, company


def _buyer(email, inn):
    company = Company.objects.create(name=f"Buyer {inn}", inn=inn)
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=False,
        can_buy=True,
    )
    return user, company


def _api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


# ── F1: the routing keystone ────────────────────────────────────────────────


@pytest.fixture
def offline_deal(lookups):
    """A seller opens a deal for a contact in their own book (the F1 scenario)."""
    seller, seller_company = _seller("f1-rep@s.test", "710000001")
    result, err = create_offline_client(
        seller=seller, company_name="Offline Buyer", contact_name="Ivan", email="ivan@off.test"
    )
    assert err is None
    resp = _api(seller).post(
        "/api/v1/crm/deals/", {"contact_id": result["contact"].id, "title": "Offline RFQ"}, format="json"
    )
    assert resp.status_code == 201, resp.content
    return seller, seller_company, Deal.objects.get(pk=resp.json()["id"])


def test_f1_offline_deal_gets_creator_routing_row(offline_deal):
    seller, seller_company, deal = offline_deal
    routing = DealSellerRouting.objects.get(deal=deal)
    assert routing.seller_company_id == seller_company.id
    # The creator owns it from the start — it is not dumped into an anonymous queue.
    assert routing.assigned_to_id == seller.id
    assert routing.assigned_at is not None


def test_f1_creator_sees_own_offline_deal_in_list(offline_deal):
    seller, _company, deal = offline_deal
    resp = _api(seller).get("/api/v1/crm/deals/", **SELLER_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    ids = [row["id"] for row in (body["results"] if isinstance(body, dict) else body)]
    assert deal.id in ids


def test_f1_creator_can_claim_own_offline_deal(offline_deal):
    seller, _company, deal = offline_deal
    resp = _api(seller).post(f"/api/v1/crm/deals/{deal.id}/claim/", **SELLER_HEADERS)
    # Already owned by the creator → idempotent success, NOT "MEMBER_REQUIRED_FOR_ACTION".
    assert resp.status_code == 200, resp.content


def test_f1_creator_can_build_quote_on_own_offline_deal(offline_deal):
    seller, _company, deal = offline_deal
    resp = _api(seller).post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json", **SELLER_HEADERS)
    assert resp.status_code == 201, resp.content
    assert Quote.objects.filter(deal=deal).exists()


def test_f1_other_seller_cannot_see_or_build_on_the_offline_deal(offline_deal):
    """Routing is per seller company — F1 must not widen visibility beyond the creator."""
    _seller_a, _company, deal = offline_deal
    intruder, _intruder_company = _seller("f1-intruder@s.test", "710000002")
    api = _api(intruder)

    body = api.get("/api/v1/crm/deals/", **SELLER_HEADERS).json()
    ids = [row["id"] for row in (body["results"] if isinstance(body, dict) else body)]
    assert deal.id not in ids

    assert api.get(f"/api/v1/crm/deals/{deal.id}/", **SELLER_HEADERS).status_code == 404
    resp = api.post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json", **SELLER_HEADERS)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "NO_ACCESS_TO_DEAL"


# ── F3: the company-less calculator draft ───────────────────────────────────


@pytest.fixture
def calculator_draft(lookups):
    seller, seller_company = _seller("f3-rep@s.test", "720000001")
    resp = _api(seller).post(
        "/api/v1/crm/deals/", {"without_client": True, "title": "Расчёт без клиента"}, format="json"
    )
    assert resp.status_code == 201, resp.content
    return seller, seller_company, Deal.objects.get(pk=resp.json()["id"])


def test_f3_creates_company_less_draft_with_routing(calculator_draft):
    seller, seller_company, deal = calculator_draft
    assert deal.company_id is None and deal.contact_id is None and deal.client_id is None
    assert DealSellerRouting.objects.filter(deal=deal, seller_company=seller_company).exists()


def test_f3_creator_can_see_and_build(calculator_draft):
    seller, _company, deal = calculator_draft
    api = _api(seller)
    assert api.get(f"/api/v1/crm/deals/{deal.id}/", **SELLER_HEADERS).status_code == 200
    resp = api.post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json", **SELLER_HEADERS)
    assert resp.status_code == 201, resp.content


def test_f3_serializer_reports_null_company_name(calculator_draft):
    seller, _company, deal = calculator_draft
    body = _api(seller).get(f"/api/v1/crm/deals/{deal.id}/", **SELLER_HEADERS).json()
    assert body["company"] is None
    assert body["company_name"] is None


def test_f3_non_seller_cannot_create_calculator_draft(lookups):
    buyer, _company = _buyer("f3-buyer@b.test", "720000009")
    resp = _api(buyer).post("/api/v1/crm/deals/", {"without_client": True, "title": "x"}, format="json")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "ONLY_SELLER_CAN_CREATE_CALCULATOR_DRAFT"


# ── F3 SECURITY: fail-closed cross-tenant negatives ─────────────────────────


def test_f3_cross_tenant_seller_cannot_reach_company_less_draft(calculator_draft):
    """THE load-bearing negative. `core/permissions.py` resolves `target_company =
    obj.deal.company`; with NULL it must DENY (`if target_company:` is falsy), and the seller
    branch must not grant either, because seller B has no routing row. Two NULLs must never
    compare as a match."""
    _seller_a, _company_a, deal = calculator_draft
    intruder, _company_b = _seller("f3-intruder@s.test", "720000002")
    api = _api(intruder)

    body = api.get("/api/v1/crm/deals/", **SELLER_HEADERS).json()
    ids = [row["id"] for row in (body["results"] if isinstance(body, dict) else body)]
    assert deal.id not in ids, "company-less draft leaked into another seller's list"

    assert api.get(f"/api/v1/crm/deals/{deal.id}/", **SELLER_HEADERS).status_code == 404
    assert api.post(f"/api/v1/crm/deals/{deal.id}/claim/", **SELLER_HEADERS).status_code in (400, 403)
    resp = api.post("/api/v1/crm/quotes/", {"deal": deal.id}, format="json", **SELLER_HEADERS)
    assert resp.status_code == 403 and resp.json()["detail"] == "NO_ACCESS_TO_DEAL"


def test_f3_unrelated_buyer_cannot_reach_company_less_draft(calculator_draft):
    """A buyer's scope is `company_id__in=<my companies>` — NULL never matches, so the draft
    is invisible. This is the "NULL is not a wildcard" assertion."""
    _seller_a, _company_a, deal = calculator_draft
    buyer, _buyer_company = _buyer("f3-outsider@b.test", "720000003")
    api = _api(buyer)

    body = api.get("/api/v1/crm/deals/").json()
    ids = [row["id"] for row in (body["results"] if isinstance(body, dict) else body)]
    assert deal.id not in ids
    assert api.get(f"/api/v1/crm/deals/{deal.id}/").status_code == 404


def test_f3_company_less_quote_object_permission_denies_foreign_seller(calculator_draft):
    """Object-level guard directly: a Quote hanging off a NULL-company deal must not fall
    through `target_company` to an accidental allow."""
    seller_a, _company_a, deal = calculator_draft
    quote = Quote.objects.create(
        deal=deal, version=1, prepared_by=seller_a, status=QuoteStatus.objects.get(code="DRAFT")
    )
    intruder, _company_b = _seller("f3-intruder2@s.test", "720000004")
    resp = _api(intruder).get(f"/api/v1/crm/quotes/{quote.id}/", **SELLER_HEADERS)
    assert resp.status_code == 404


# ── F3: send is blocked until a recipient exists ────────────────────────────


def test_f3_send_refuses_company_less_draft_with_recipient_required(calculator_draft):
    from crm.services.quotes import QuoteLifecycleService

    seller, seller_company, deal = calculator_draft
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        prepared_by=seller,
        seller_company=seller_company,
        status=QuoteStatus.objects.get(code="READY_TO_SEND"),
    )
    with pytest.raises(ValueError) as exc:
        QuoteLifecycleService.send_to_client(quote.id, seller)
    assert str(exc.value) == "RECIPIENT_REQUIRED"


def test_f3_client_display_name_degrades_without_company(calculator_draft):
    """The notification/audit strings used to be `quote.deal.company.name` — a crash on NULL."""
    from crm.services.quotes import _quote_client_display_name

    seller, _company, deal = calculator_draft
    quote = Quote.objects.create(deal=deal, version=1, prepared_by=seller, status=QuoteStatus.objects.get(code="DRAFT"))
    assert _quote_client_display_name(quote) == "Клиент"


def test_f3_client_display_name_prefers_company_then_contact(offline_deal):
    from crm.services.quotes import _quote_client_display_name

    seller, _company, deal = offline_deal
    quote = Quote.objects.create(deal=deal, version=1, prepared_by=seller, status=QuoteStatus.objects.get(code="DRAFT"))
    assert _quote_client_display_name(quote) == "Offline Buyer"
    deal.company = None
    deal.save(update_fields=["company"])
    quote.refresh_from_db()
    assert _quote_client_display_name(quote) == "Ivan"


# ── F4: promote-invite backfills historical deals ───────────────────────────


def test_f4_invite_acceptance_backfills_client_on_historical_deals(offline_deal):
    from accounts.services.clients import _hash_invite_token, send_client_invite
    from accounts.services.profile import submit_company_profile

    seller, _seller_company, deal = offline_deal
    assert deal.client_id is None

    invite, err = send_client_invite(seller=seller, contact_id=deal.contact_id)
    assert err is None
    token = "raw-token-for-f4"
    invite.token_hash = _hash_invite_token(token)
    invite.save(update_fields=["token_hash"])

    invitee = CustomUser.objects.create_user(
        email="ivan@off.test", username="ivan@off.test", password="x", is_active=True
    )
    _user, err = submit_company_profile(invitee, company_name="ignored", invite_token=token)
    assert err is None

    deal.refresh_from_db()
    assert deal.client_id == invitee.id, "the newly-registered client cannot see the КП sent earlier"


def test_f4_backfill_never_repoints_a_deal_that_already_has_a_client(offline_deal):
    from crm.services.deals import link_registered_client_to_contact_deals

    _seller, _company, deal = offline_deal
    incumbent = CustomUser.objects.create_user(email="incumbent@t.test", username="incumbent@t.test", password="x")
    deal.client = incumbent
    deal.save(update_fields=["client"])

    newcomer = CustomUser.objects.create_user(email="newcomer@t.test", username="newcomer@t.test", password="x")
    updated = link_registered_client_to_contact_deals(deal.contact_id, newcomer)

    assert updated == 0
    deal.refresh_from_db()
    assert deal.client_id == incumbent.id

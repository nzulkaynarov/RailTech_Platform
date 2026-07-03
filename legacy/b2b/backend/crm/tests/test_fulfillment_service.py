"""Service-level tests for crm.services.fulfillment.

Covers `ensure_fulfillment` (creation + idempotency) and every authorization /
side-effect branch of `update_fulfillment_status`:

  * platform-admin viewer  → ADMIN_VIEWER_CANNOT_ACT
  * unknown status code     → FULFILLMENT_INVALID_STATUS
  * buyer-side statuses (ACCEPTED / DISPUTED) gated by can_buy on deal.company
  * seller-side statuses (SHIPPED / DELIVERED) gated by DealSellerRouting
  * superuser bypasses both gates
  * shipped_at / delivered_at / accepted_at stamping (not overwritten on repeat)
  * **extra fields persisted; a None value is ignored
  * ACCEPTED auto-closes the deal as CLOSED_WON

Runs with --nomigrations (see pyproject addopts), so the data migration that
normally seeds the lookup rows never runs — the `lookups` fixture recreates the
codes the flow asserts on, exactly like test_golden_path.py.
"""

import datetime

import pytest

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm import services as crm_services
from crm.constants import DealStageCode, FulfillmentStatusCode
from crm.models import (
    Contract,
    ContractStatus,
    Deal,
    DealSellerRouting,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Quote,
    QuoteStatus,
)


@pytest.fixture
def lookups(db):
    for code in [
        DealStageCode.DRAFT,
        DealStageCode.CONTRACT_SIGNED,
        DealStageCode.CLOSED_WON,
        DealStageCode.CLOSED_LOST,
    ]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in FulfillmentStatusCode.values:
        FulfillmentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    for code in ["DRAFT", "SIGNED", "CANCELLED"]:
        ContractStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})


def _member(company, email, *, can_sell=False, can_buy=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x", is_active=True)
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


@pytest.fixture
def world(lookups):
    """A buyer company with a can_buy member + deal, and a can_sell seller company."""
    l2 = VerificationStatus.objects.get(code="L2_VERIFIED")
    buyer_co = Company.objects.create(name="Buyer Co", inn="B100", verification_status=l2)
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    buyer = _member(buyer_co, "buyer@t.test", can_buy=True)

    seller_co = Company.objects.create(name="Seller Co", inn="S100", verification_status=l2)
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller = _member(seller_co, "seller@t.test", can_sell=True)

    other_seller_co = Company.objects.create(name="Other Seller Co", inn="S200", verification_status=l2)
    other_seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    other_seller = _member(other_seller_co, "other-seller@t.test", can_sell=True)

    superuser = CustomUser.objects.create_user(
        email="root@t.test", username="root@t.test", password="x", is_active=True, is_superuser=True, is_staff=True
    )
    admin_viewer = CustomUser.objects.create_user(
        email="admin@t.test",
        username="admin@t.test",
        password="x",
        is_active=True,
        role=SystemRole.objects.get(code="ADMIN"),
    )

    deal = Deal.objects.create(
        title="Fulfillment deal", company=buyer_co, stage=DealStage.objects.get(code=DealStageCode.DRAFT)
    )
    return {
        "buyer_co": buyer_co,
        "buyer": buyer,
        "seller_co": seller_co,
        "seller": seller,
        "other_seller": other_seller,
        "superuser": superuser,
        "admin_viewer": admin_viewer,
        "deal": deal,
    }


# ── ensure_fulfillment ──────────────────────────────────────────────────────


@pytest.mark.django_db
def test_ensure_fulfillment_creates_pending(world):
    obj = crm_services.ensure_fulfillment(world["deal"])
    assert obj.deal_id == world["deal"].id
    assert obj.status.code == FulfillmentStatusCode.PENDING


@pytest.mark.django_db
def test_ensure_fulfillment_is_idempotent(world):
    first = crm_services.ensure_fulfillment(world["deal"])
    second = crm_services.ensure_fulfillment(world["deal"])
    assert first.pk == second.pk
    assert Fulfillment.objects.filter(deal=world["deal"]).count() == 1


# ── update_fulfillment_status: authorization branches ───────────────────────


@pytest.mark.django_db
def test_platform_admin_viewer_cannot_act(world):
    crm_services.ensure_fulfillment(world["deal"])
    obj, err = crm_services.update_fulfillment_status(
        world["deal"].id, world["admin_viewer"], FulfillmentStatusCode.SHIPPED
    )
    assert obj is None
    assert err == "ADMIN_VIEWER_CANNOT_ACT"


@pytest.mark.django_db
def test_unknown_status_rejected(world):
    crm_services.ensure_fulfillment(world["deal"])
    obj, err = crm_services.update_fulfillment_status(world["deal"].id, world["superuser"], "NOT_A_STATUS")
    assert obj is None
    assert err == "FULFILLMENT_INVALID_STATUS"


@pytest.mark.django_db
@pytest.mark.parametrize("status_code", [FulfillmentStatusCode.ACCEPTED, FulfillmentStatusCode.DISPUTED])
def test_buyer_status_by_non_buyer_rejected(world, status_code):
    """A seller (not a member of the buyer company) cannot drive a buyer-side status."""
    crm_services.ensure_fulfillment(world["deal"])
    obj, err = crm_services.update_fulfillment_status(world["deal"].id, world["seller"], status_code)
    assert obj is None
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


@pytest.mark.django_db
def test_disputed_by_buyer_member_succeeds(world):
    crm_services.ensure_fulfillment(world["deal"])
    obj, err = crm_services.update_fulfillment_status(world["deal"].id, world["buyer"], FulfillmentStatusCode.DISPUTED)
    assert err is None
    assert obj.status.code == FulfillmentStatusCode.DISPUTED


@pytest.mark.django_db
def test_seller_status_by_unrouted_seller_rejected(world):
    """A can_sell seller whose company is NOT routed to the deal cannot ship it."""
    crm_services.ensure_fulfillment(world["deal"])
    obj, err = crm_services.update_fulfillment_status(
        world["deal"].id, world["other_seller"], FulfillmentStatusCode.SHIPPED
    )
    assert obj is None
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "status_code,stamp_field",
    [
        (FulfillmentStatusCode.SHIPPED, "shipped_at"),
        (FulfillmentStatusCode.DELIVERED, "delivered_at"),
    ],
)
def test_seller_status_by_routed_seller_succeeds(world, status_code, stamp_field):
    DealSellerRouting.objects.create(deal=world["deal"], seller_company=world["seller_co"])
    crm_services.ensure_fulfillment(world["deal"])
    obj, err = crm_services.update_fulfillment_status(world["deal"].id, world["seller"], status_code)
    assert err is None
    assert obj.status.code == status_code
    assert getattr(obj, stamp_field) is not None


@pytest.mark.django_db
def test_superuser_authorized_for_any_status(world):
    """Superuser is the DBA bypass — authorized for a seller status with no routing at all."""
    crm_services.ensure_fulfillment(world["deal"])
    obj, err = crm_services.update_fulfillment_status(
        world["deal"].id, world["superuser"], FulfillmentStatusCode.DELIVERED
    )
    assert err is None
    assert obj.status.code == FulfillmentStatusCode.DELIVERED


# ── update_fulfillment_status: side effects ─────────────────────────────────


@pytest.mark.django_db
def test_timestamp_not_overwritten_on_repeat(world):
    DealSellerRouting.objects.create(deal=world["deal"], seller_company=world["seller_co"])
    crm_services.ensure_fulfillment(world["deal"])
    obj, err = crm_services.update_fulfillment_status(world["deal"].id, world["seller"], FulfillmentStatusCode.SHIPPED)
    assert err is None
    first_shipped_at = obj.shipped_at
    assert first_shipped_at is not None

    # A repeat SHIPPED must NOT re-stamp shipped_at (idempotent timestamp).
    obj2, err2 = crm_services.update_fulfillment_status(
        world["deal"].id, world["seller"], FulfillmentStatusCode.SHIPPED
    )
    assert err2 is None
    assert obj2.shipped_at == first_shipped_at


@pytest.mark.django_db
def test_extra_fields_persisted_and_none_ignored(world):
    DealSellerRouting.objects.create(deal=world["deal"], seller_company=world["seller_co"])
    crm_services.ensure_fulfillment(world["deal"])
    eta = datetime.date(2026, 8, 1)
    obj, err = crm_services.update_fulfillment_status(
        world["deal"].id,
        world["seller"],
        FulfillmentStatusCode.SHIPPED,
        tracking_number="TN-123",
        carrier="DHL",
        expected_delivery_date=eta,
        notes="handle with care",
    )
    assert err is None
    assert obj.tracking_number == "TN-123"
    assert obj.carrier == "DHL"
    assert obj.expected_delivery_date == eta
    assert obj.notes == "handle with care"

    # A None value in extra must be ignored (carrier stays "DHL"), other keys still apply.
    obj2, err2 = crm_services.update_fulfillment_status(
        world["deal"].id,
        world["seller"],
        FulfillmentStatusCode.DELIVERED,
        carrier=None,
        notes="delivered ok",
    )
    assert err2 is None
    assert obj2.carrier == "DHL"
    assert obj2.notes == "delivered ok"


@pytest.mark.django_db
def test_accepted_closes_deal_won(world):
    """ACCEPTED by the buyer auto-closes the deal — requires CONTRACT_SIGNED + a signed Contract."""
    deal = world["deal"]
    deal.stage = DealStage.objects.get(code=DealStageCode.CONTRACT_SIGNED)
    deal.save(update_fields=["stage"])
    quote = Quote.objects.create(deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"))
    Contract.objects.create(deal=deal, quote=quote, number="C-1", status=ContractStatus.objects.get(code="SIGNED"))

    crm_services.ensure_fulfillment(deal)
    obj, err = crm_services.update_fulfillment_status(deal.id, world["buyer"], FulfillmentStatusCode.ACCEPTED)
    assert err is None
    assert obj.status.code == FulfillmentStatusCode.ACCEPTED
    assert obj.accepted_at is not None

    deal.refresh_from_db()
    assert deal.stage.code == DealStageCode.CLOSED_WON

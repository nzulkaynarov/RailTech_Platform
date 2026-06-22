"""Seller team gets notified when a new заявка opens (Deal → RFQ_OPEN).

Owner-reported: notifications felt dead on the seller side. Cause: every
seller-facing notification targeted `deal.manager`, but in the single-seller
model a buyer's deal has no manager → the seller's bell stayed empty. Now the
RFQ_OPEN transition fans out to the seller team.
"""

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, VerificationStatus, WorkspaceRole
from crm.models import Deal, DealStage
from notifications.models import Notification, NotificationType


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2"})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "RFQ", "sort_order": 20})
    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info"})


def _member(company, email, *, can_sell=False, can_buy=False):
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True, is_primary=True, can_sell=can_sell, can_buy=can_buy,
    )
    return user


@pytest.fixture
def parties(lookups):
    seller_co = Company.objects.create(name="Seller Co", inn="S1")
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller = _member(seller_co, "seller@t.test", can_sell=True)

    buyer_co = Company.objects.create(name="Buyer Co", inn="B1")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    buyer = _member(buyer_co, "buyer@t.test", can_buy=True)

    deal = Deal.objects.create(
        title="z", company=buyer_co, client=buyer, stage=DealStage.objects.get(code="DRAFT")
    )
    return {"seller": seller, "buyer": buyer, "deal": deal}


@pytest.mark.django_db
def test_seller_notified_when_request_opens(parties):
    seller, buyer, deal = parties["seller"], parties["buyer"], parties["deal"]
    assert not Notification.objects.filter(user=seller).exists()  # nothing while DRAFT

    deal.stage = DealStage.objects.get(code="RFQ_OPEN")
    deal.save()

    seller_notifs = Notification.objects.filter(user=seller)
    assert seller_notifs.count() == 1
    assert "Новая заявка" in seller_notifs.first().title
    # The buyer still gets their own stage-change notification.
    assert Notification.objects.filter(user=buyer, title="Статус сделки изменён").exists()


@pytest.mark.django_db
def test_no_seller_spam_on_non_rfq_transitions(parties):
    seller, deal = parties["seller"], parties["deal"]
    deal.stage = DealStage.objects.get(code="RFQ_OPEN")
    deal.save()
    baseline = Notification.objects.filter(user=seller).count()
    # A later transition back to DRAFT must NOT mint another "Новая заявка".
    deal.stage = DealStage.objects.get(code="DRAFT")
    deal.save()
    assert Notification.objects.filter(user=seller).count() == baseline

"""Contract sign-side hints (review MEDIUM fix): the viewer's signable side is derived from their
relationship to the contract's deal — NOT the SPA page context: the buyer side signs as client,
own-company staff (the single seller) sign as manager, and the hint never drifts from what
sign_contract_by_* actually authorizes (shared predicates)."""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from crm.models import Contract, ContractStatus, Deal, DealStage, Quote, QuoteStatus
from crm.services.contracts import viewer_can_sign_client, viewer_can_sign_manager

pytestmark = pytest.mark.django_db


@pytest.fixture
def contract_world(db, grant):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    DealStage.objects.get_or_create(code="CONTRACT_SIGNED", defaults={"name": "CS", "sort_order": 60})
    QuoteStatus.objects.get_or_create(code="APPROVED", defaults={"name": "Approved", "sort_order": 50})
    status = ContractStatus.objects.get_or_create(code="PENDING_CLIENT", defaults={"name": "PC", "sort_order": 10})[0]

    buyer = Company.objects.create(name="Buyer LLC", inn="6600000001")
    buyer.types.add(CompanyType.objects.get(code="CLIENT"))
    seller = Company.objects.create(name="Own LLC", inn="3000000001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))

    def member(co, email, **caps):
        user = CustomUser.objects.create_user(email=email, username=email, password="pw")
        CompanyMember.objects.create(
            user=user, company=co, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, **caps
        )
        return user

    buyer_user = member(buyer, "b@t.test", can_buy=True)
    seller_user = member(seller, "s@t.test", can_sell=True)
    grant(seller_user, "contract.sign")  # M1-ERP-05: подпись от компании — право роли, не флаг can_sell

    deal = Deal.objects.create(title="D", company=buyer, stage=DealStage.objects.get(code="CONTRACT_SIGNED"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="APPROVED"),
        seller_company=seller,
        subtotal_excl_vat=Decimal("100"),
        vat_amount=Decimal("12"),
        total_incl_vat=Decimal("112"),
    )
    contract = Contract.objects.create(
        deal=deal, quote=quote, number="CT-1", total_amount=Decimal("112"), status=status
    )
    return {"buyer_user": buyer_user, "seller_user": seller_user, "contract": contract, "seller_co": seller}


def test_buyer_can_sign_client_not_manager(contract_world):
    u, c = contract_world["buyer_user"], contract_world["contract"]
    assert viewer_can_sign_client(u, c) is True
    assert viewer_can_sign_manager(u, c) is False


def test_staff_can_sign_manager_not_client(contract_world):
    u, c = contract_world["seller_user"], contract_world["contract"]
    assert viewer_can_sign_manager(u, c) is True
    assert viewer_can_sign_client(u, c) is False


def test_staff_without_contract_sign_cannot_sign_manager(contract_world):
    """M1-ERP-05: флаг `can_sell` подписи не даёт — только право роли `contract.sign`."""
    seller = contract_world["seller_co"]
    user = CustomUser.objects.create_user(email="calc@t.test", username="calc@t.test", password="pw")
    CompanyMember.objects.create(
        user=user, company=seller, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_sell=True
    )
    assert viewer_can_sign_manager(user, contract_world["contract"]) is False


def test_unrelated_user_signs_neither_side(contract_world):
    stranger = CustomUser.objects.create_user(email="x@t.test", username="x@t.test", password="pw")
    c = contract_world["contract"]
    assert viewer_can_sign_client(stranger, c) is False
    assert viewer_can_sign_manager(stranger, c) is False


def test_outsider_with_sell_flag_cannot_sign_manager(contract_world):
    """Audit H3: a can_sell member of ANOTHER company (not own-company staff) cannot sign the
    seller side of this contract — the side is staff of the own company, not the membership flag."""
    other = Company.objects.create(name="Other Client", inn="3000000009")
    other.types.add(CompanyType.objects.get(code="CLIENT"))
    other_user = CustomUser.objects.create_user(email="o@t.test", username="o@t.test", password="pw")
    CompanyMember.objects.create(
        user=other_user, company=other, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, can_sell=True
    )
    assert viewer_can_sign_manager(other_user, contract_world["contract"]) is False


def test_serializer_exposes_side_independent_of_context(contract_world):
    from rest_framework.test import APIRequestFactory

    from crm.serializers import ContractSerializer

    # Own-company staff get the manager-sign hint — the side is computed by the server.
    request = APIRequestFactory().get("/")
    request.user = contract_world["seller_user"]
    data = ContractSerializer(contract_world["contract"], context={"request": request}).data
    assert data["viewer_can_sign_manager"] is True
    assert data["viewer_can_sign_client"] is False

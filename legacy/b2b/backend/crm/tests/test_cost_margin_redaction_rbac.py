"""КП cost/margin redaction keyed on the quote.view_cost_margin CompanyRole permission
(rbac-roles-design-2026-06-25, item 3).

A seller-team member WITHOUT quote.view_cost_margin must NOT see cost/margin fields even on
their OWN company's quote; a member of the same company WITH the permission still does.
This exercises crm.serializers.QuoteItemSerializer.to_representation →
accounts.services.permissions.can_view_quote_costs_for → member_has_permission.
"""

import pytest
from rest_framework.test import APIRequestFactory

from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyType,
    CustomUser,
    WorkspaceRole,
)
from crm.models import Deal, DealStage, Quote, QuoteItem
from crm.serializers import QuoteItemSerializer

_COST_FIELDS = ("frozen_base_price", "logistics_cost", "customs_duty", "margin_percent", "landed_cost")


def _seller_member(company, email, *, perms):
    ws = WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 50})[0]
    role = CompanyRole.objects.create(company=company, name=f"role-{email}", permissions=perms)
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    # can_sell defaults True everywhere; the point is the CompanyRole perm gates cost visibility.
    CompanyMember.objects.create(
        user=user, company=company, role=ws, company_role=role, is_active=True, can_sell=True, can_buy=False
    )
    return user


@pytest.fixture
def quote_item(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    seller_co = Company.objects.create(name="SellerCo")
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    # prepared_by anchors the quote to seller_co (can_view_quote_costs_for intersects the
    # preparer's company with the viewer's).
    preparer = _seller_member(seller_co, "preparer@s.test", perms=["quote.view_cost_margin"])
    stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    deal = Deal.objects.create(title="d", company=seller_co, client=preparer, stage=stage)
    quote = Quote.objects.create(deal=deal, version=1, prepared_by=preparer)
    # Build the item in memory — QuoteItem.save() runs the FX/calc engine which needs a full
    # currency setup; the redaction only reads attributes via serializer.to_representation,
    # so an unsaved instance is enough and keeps the test focused on the permission gate.
    item = QuoteItem(
        quote=quote, quantity=1, frozen_base_price="100.00", logistics_cost="5.00",
        customs_duty="2.00", margin_percent="20.00", landed_cost="107.00",
    )
    return seller_co, item


def _serialize_as(user, item):
    request = APIRequestFactory().get("/")
    request.user = user
    return QuoteItemSerializer(item, context={"request": request}).data


@pytest.mark.django_db
def test_cost_hidden_from_member_without_permission(quote_item):
    seller_co, item = quote_item
    restricted = _seller_member(seller_co, "nosee@s.test", perms=[])  # no quote.view_cost_margin
    data = _serialize_as(restricted, item)
    for field in _COST_FIELDS:
        assert field not in data, f"{field} leaked to a member without quote.view_cost_margin"


@pytest.mark.django_db
def test_cost_shown_to_member_with_permission(quote_item):
    seller_co, item = quote_item
    privileged = _seller_member(seller_co, "see@s.test", perms=["quote.view_cost_margin"])
    data = _serialize_as(privileged, item)
    for field in _COST_FIELDS:
        assert field in data, f"{field} hidden from a member WITH quote.view_cost_margin"

"""КП cost/margin redaction keyed on the quote.view_cost_margin CompanyRole permission
(rbac-roles-design-2026-06-25, item 3).

A seller-team member WITHOUT quote.view_cost_margin must NOT see cost/margin fields even on
their OWN company's quote; a member of the same company WITH the permission still does.
This exercises crm.serializers.QuoteItemSerializer.to_representation →
accounts.services.permissions.can_view_quote_costs_for → member_has_permission.
"""

import pytest
from rest_framework.test import APIRequestFactory

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from crm.models import ChargeType, Deal, DealStage, Quote, QuoteCharge, QuoteItem
from crm.serializers import QuoteChargeSerializer, QuoteItemSerializer

_COST_FIELDS = ("frozen_base_price", "logistics_cost", "customs_duty", "margin_percent", "landed_cost")
# Per-charge cost / breakdown the standalone charge endpoint must also redact (cascade audit).
_CHARGE_COST_FIELDS = ("cost_amount", "resolved_base", "resolved_amount", "amount", "rate_percent")


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
        quote=quote,
        quantity=1,
        frozen_base_price="100.00",
        logistics_cost="5.00",
        customs_duty="2.00",
        margin_percent="20.00",
        landed_cost="107.00",
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


# ─── QuoteCharge redaction (charge-cascade audit: cost_amount/resolved_* must not leak) ──────
@pytest.fixture
def quote_charge(db):
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    seller_co = Company.objects.create(name="ChargeCo")
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    preparer = _seller_member(seller_co, "cprep@s.test", perms=["quote.view_cost_margin"])
    stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    deal = Deal.objects.create(title="cd", company=seller_co, client=preparer, stage=stage)
    quote = Quote.objects.create(deal=deal, version=1, prepared_by=preparer)
    ctype = ChargeType.objects.get_or_create(code="FREIGHT", defaults={"name": "Freight", "sort_order": 10})[0]
    charge = QuoteCharge(
        quote=quote,
        charge_type=ctype,
        rate_percent="10.00",
        amount="0.00",
        cost_amount="400000.00",
        resolved_base="950000.00",
        resolved_amount="95000.00",
    )
    return seller_co, charge


def _serialize_charge_as(user, charge):
    request = APIRequestFactory().get("/")
    request.user = user
    return QuoteChargeSerializer(charge, context={"request": request}).data


@pytest.mark.django_db
def test_charge_cost_hidden_from_member_without_permission(quote_charge):
    seller_co, charge = quote_charge
    restricted = _seller_member(seller_co, "cnosee@s.test", perms=[])
    data = _serialize_charge_as(restricted, charge)
    for field in _CHARGE_COST_FIELDS:
        assert field not in data, f"{field} leaked on the charge endpoint to a non-cost-viewer"


@pytest.mark.django_db
def test_charge_cost_shown_to_member_with_permission(quote_charge):
    seller_co, charge = quote_charge
    privileged = _seller_member(seller_co, "csee@s.test", perms=["quote.view_cost_margin"])
    data = _serialize_charge_as(privileged, charge)
    for field in _CHARGE_COST_FIELDS:
        assert field in data, f"{field} hidden from a charge cost-viewer"


# ─── QUOTE-LEVEL redaction (audit #3): margin_percent + fx_snapshot/fx_manual ────────────────
_QUOTE_COST_FIELDS = ("margin_percent", "fx_snapshot", "fx_manual", "charges_total")


@pytest.fixture
def quote_row(db):
    from crm.serializers import QuoteSerializer  # noqa: F401 — ensure importable

    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 10})
    seller_co = Company.objects.create(name="QuoteCo")
    seller_co.types.add(CompanyType.objects.get(code="SUPPLIER"))
    preparer = _seller_member(seller_co, "qprep@s.test", perms=["quote.view_cost_margin"])
    stage = DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})[0]
    deal = Deal.objects.create(title="qd", company=seller_co, client=preparer, stage=stage)
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        prepared_by=preparer,
        margin_percent="22.00",
        fx_snapshot={"USD": "12650"},
        fx_manual={"USD": "12800"},
    )
    return seller_co, quote


def _serialize_quote_as(user, quote):
    from crm.serializers import QuoteSerializer

    request = APIRequestFactory().get("/")
    request.user = user
    return QuoteSerializer(quote, context={"request": request}).data


@pytest.mark.django_db
def test_quote_margin_fx_hidden_from_non_cost_viewer(quote_row):
    """A buyer / a seller-team member without quote.view_cost_margin must not receive the
    whole-КП markup or the FX cost-conversion rates (they reconstruct landed cost)."""
    seller_co, quote = quote_row
    restricted = _seller_member(seller_co, "qnosee@s.test", perms=[])
    data = _serialize_quote_as(restricted, quote)
    for field in _QUOTE_COST_FIELDS:
        assert field not in data, f"{field} leaked to a non-cost viewer at the quote level"


@pytest.mark.django_db
def test_quote_margin_fx_shown_to_cost_viewer(quote_row):
    seller_co, quote = quote_row
    privileged = _seller_member(seller_co, "qsee@s.test", perms=["quote.view_cost_margin"])
    data = _serialize_quote_as(privileged, quote)
    for field in ("margin_percent", "fx_snapshot", "fx_manual"):
        assert field in data, f"{field} hidden from a cost viewer at the quote level"


# ─── Администратор = is_superuser (M1-ERP-02 волна 1a: операторской плоскости нет) ──────────


def _administrator(email="root@s.test"):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True, is_superuser=True)


def _legacy_admin_role_user(email="legacy-admin@s.test"):
    """Носитель SystemRole=ADMIN без `is_superuser` и без членства — после M1-ERP-02 это не
    администратор: прежнее «ADMIN без компании = оператор-наблюдатель» видело себестоимость."""
    from accounts.models import SystemRole

    role, _ = SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 1})
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True, role=role)


@pytest.mark.django_db
def test_administrator_sees_item_cost_without_membership(quote_item):
    _seller_co, item = quote_item
    data = _serialize_as(_administrator(), item)
    for field in _COST_FIELDS:
        assert field in data, f"{field} hidden from the administrator (is_superuser)"


@pytest.mark.django_db
def test_administrator_sees_quote_margin_and_fx(quote_row):
    _seller_co, quote = quote_row
    data = _serialize_quote_as(_administrator(), quote)
    for field in ("margin_percent", "fx_snapshot", "fx_manual"):
        assert field in data, f"{field} hidden from the administrator at the quote level"


@pytest.mark.django_db
def test_legacy_admin_role_without_superuser_sees_no_item_cost(quote_item):
    _seller_co, item = quote_item
    data = _serialize_as(_legacy_admin_role_user(), item)
    for field in _COST_FIELDS:
        assert field not in data, f"{field} leaked to SystemRole=ADMIN without is_superuser"


@pytest.mark.django_db
def test_legacy_admin_role_without_superuser_sees_no_quote_margin(quote_row):
    _seller_co, quote = quote_row
    data = _serialize_quote_as(_legacy_admin_role_user(), quote)
    for field in _QUOTE_COST_FIELDS:
        assert field not in data, f"{field} leaked to SystemRole=ADMIN at the quote level"

"""Company Role+Permission-set model + member_has_permission (RBAC matrix, phase 1)."""

import pytest

from accounts.models import Company, CompanyMember, CompanyRole, CustomUser, WorkspaceRole
from accounts.services import member_has_permission


@pytest.fixture
def company(db):
    return Company.objects.create(name="Acme")


def _member(company, email, *, role=None, can_sell=True, can_buy=True, wsrole_code="MEMBER"):
    ws = WorkspaceRole.objects.get_or_create(code=wsrole_code, defaults={"name": wsrole_code, "sort_order": 10})[0]
    user = CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)
    return CompanyMember.objects.create(
        user=user, company=company, role=ws, company_role=role,
        is_active=True, can_sell=can_sell, can_buy=can_buy,
    )


@pytest.mark.django_db
def test_default_templates_have_five_roles_with_one_system(company):
    """The seeded default set = 5 role templates, exactly one immutable «Администратор компании»."""
    from accounts.constants import COMPANY_ADMIN_ROLE_NAME, ROLE_TEMPLATES

    assert len(ROLE_TEMPLATES) == 5
    for name, perms in ROLE_TEMPLATES.items():
        CompanyRole.objects.create(
            company=company, name=name, permissions=list(perms), is_system=name == COMPANY_ADMIN_ROLE_NAME
        )
    roles = CompanyRole.objects.filter(company=company)
    assert roles.count() == 5
    system_roles = roles.filter(is_system=True)
    assert system_roles.count() == 1
    assert system_roles.first().name == COMPANY_ADMIN_ROLE_NAME
    # The Наблюдатель template carries no sensitive permission.
    assert roles.get(name="Наблюдатель").permissions == []


@pytest.mark.django_db
def test_sales_member_can_send_quote_but_not_sign_contract(company):
    """A member mapped onto the «Менеджер по продажам» template can quote.send but not contract.sign."""
    from accounts.constants import ROLE_TEMPLATES

    sales_role = CompanyRole.objects.create(
        company=company, name="Менеджер по продажам", permissions=list(ROLE_TEMPLATES["Менеджер по продажам"])
    )
    sales = _member(company, "sales@a.test", role=sales_role, can_sell=False, can_buy=False)
    assert member_has_permission(sales.user, company.id, "quote.send") is True
    assert member_has_permission(sales.user, company.id, "contract.sign") is False
    assert member_has_permission(sales.user, company.id, "payment.record") is False


@pytest.mark.django_db
def test_viewer_member_can_do_nothing_sensitive(company):
    """A «Наблюдатель» (read-only) member holds none of the sensitive permissions."""
    viewer_role = CompanyRole.objects.create(company=company, name="Наблюдатель", permissions=[])
    viewer = _member(company, "view@a.test", role=viewer_role, can_sell=False, can_buy=False)
    for perm in ("quote.send", "quote.approve", "contract.sign", "payment.record", "team.manage", "data.export"):
        assert member_has_permission(viewer.user, company.id, perm) is False


@pytest.mark.django_db
def test_company_role_has_perm(company):
    role = CompanyRole.objects.create(company=company, name="Sales", permissions=["quote.send", "quote.build"])
    assert role.has_perm("quote.send") is True
    assert role.has_perm("payment.record") is False


@pytest.mark.django_db
def test_system_role_has_all(company):
    role = CompanyRole.objects.create(company=company, name="Admin", permissions=[], is_system=True)
    assert role.has_perm("anything.at.all") is True


@pytest.mark.django_db
def test_member_permission_from_company_role(company):
    role = CompanyRole.objects.create(company=company, name="Sales", permissions=["quote.send"])
    m = _member(company, "s@a.test", role=role)
    assert member_has_permission(m.user, company.id, "quote.send") is True
    assert member_has_permission(m.user, company.id, "payment.record") is False


@pytest.mark.django_db
def test_legacy_fallback_when_no_company_role(company):
    # No company_role → derive from can_sell/can_buy.
    seller = _member(company, "sell@a.test", role=None, can_sell=True, can_buy=False)
    assert member_has_permission(seller.user, company.id, "quote.send") is True       # sell perm
    assert member_has_permission(seller.user, company.id, "contract.sign") is False   # buy perm
    assert member_has_permission(seller.user, company.id, "team.manage") is False     # admin perm


@pytest.mark.django_db
def test_legacy_owner_has_all(company):
    owner = _member(company, "own@a.test", role=None, wsrole_code="OWNER")
    assert member_has_permission(owner.user, company.id, "team.manage") is True
    assert member_has_permission(owner.user, company.id, "settings.edit") is True


@pytest.mark.django_db
def test_non_member_denied(company):
    outsider = CustomUser.objects.create_user(email="out@x.test", username="out@x.test", password="pw", is_active=True)
    assert member_has_permission(outsider, company.id, "quote.send") is False


@pytest.mark.django_db
def test_role_name_unique_per_company(company):
    CompanyRole.objects.create(company=company, name="Dup", permissions=[])
    from django.db import IntegrityError

    with pytest.raises(IntegrityError):
        CompanyRole.objects.create(company=company, name="Dup", permissions=[])


@pytest.mark.django_db
def test_can_view_quote_costs_gated_by_permission(db):
    """The КП cost/margin gate: a seller-team member sees margin only with quote.view_cost_margin."""
    from accounts.models import CompanyType
    from accounts.services.permissions import can_view_quote_costs

    seller_co = Company.objects.create(name="SellerCo")
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 1})[0]
    seller_co.types.add(supplier_type)

    with_perm = CompanyRole.objects.create(company=seller_co, name="Sales", permissions=["quote.view_cost_margin"])
    without_perm = CompanyRole.objects.create(company=seller_co, name="Viewer", permissions=[])

    privileged = _member(seller_co, "see@s.test", role=with_perm, can_sell=False, can_buy=False)
    restricted = _member(seller_co, "nosee@s.test", role=without_perm, can_sell=False, can_buy=False)

    assert can_view_quote_costs(privileged.user) is True
    assert can_view_quote_costs(restricted.user) is False  # seller-team but no margin permission


def test_can_edit_quote_pricing_gated_by_permission(db):
    """Audit H2: КП pricing writes require quote.edit_pricing — a can_sell view-only role
    (e.g. Наблюдатель) must NOT edit price/margin/charges, even though can_sell defaults True."""
    from accounts.models import CompanyType
    from accounts.services.permissions import can_edit_quote_pricing

    seller_co = Company.objects.create(name="SellerCoH2")
    supplier_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 1})[0]
    seller_co.types.add(supplier_type)

    with_perm = CompanyRole.objects.create(company=seller_co, name="Sales", permissions=["quote.edit_pricing"])
    without_perm = CompanyRole.objects.create(company=seller_co, name="Viewer", permissions=[])

    editor = _member(seller_co, "edit@s.test", role=with_perm, can_sell=True, can_buy=False)
    viewer = _member(seller_co, "view@s.test", role=without_perm, can_sell=True, can_buy=False)

    assert can_edit_quote_pricing(editor.user) is True
    assert can_edit_quote_pricing(viewer.user) is False

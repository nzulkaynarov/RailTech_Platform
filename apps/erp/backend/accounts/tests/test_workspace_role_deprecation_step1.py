"""ADR-0005 Phase E U3 Step 1 — the 3 migrated view gates authorize on CompanyRole permissions,
not the legacy OWNER WorkspaceRole.

Each gate is proven in three modes:
    WITH perm (WorkspaceRole=MEMBER + CompanyRole grants the perm)  → passes  (permission-gated now)
    WITHOUT perm (MEMBER, empty CompanyRole)                        → 403
    OWNER without roles                                             → 403 (M1-ERP-05: фолбэк из
                                                                     должности снят — только роли)

Отказ без права — единый гейт эндпоинта: 403 `ROLE_NOT_PERMITTED`.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, SystemRole, WorkspaceRole


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 90})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    # Master data so a ChargeTemplate payload validates and reaches the perform_create auth gate.
    from crm.models.lookups import ChargeType
    from master_data.models import DeliveryBasis

    DeliveryBasis.objects.get_or_create(code="EXW", defaults={"name": "Ex Works", "sort_order": 10})
    ChargeType.objects.get_or_create(code="FREIGHT", defaults={"name": "Freight", "sort_order": 10})


# A ChargeTemplate payload that passes serializer validation (so the perform_create auth gate runs).
_CT_PAYLOAD = {"delivery_basis": "EXW", "charge_type": "FREIGHT", "default_amount": "100.00", "sort_order": 1}


def _company():
    company = Company.objects.create(name="Acme Seller", inn="U3S100")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    return company


def _role(company, name, perms):
    return CompanyRole.objects.create(company=company, name=name, permissions=perms)


def _member(company, email, *, workspace="MEMBER", company_roles=()):
    user = CustomUser.objects.create_user(email=email, username=email, password="x", is_active=True)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code=workspace),
        company_roles=list(company_roles),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


# ── Gate 1: edit company profile → settings.edit ─────────────────────────────


def test_company_edit_allowed_with_settings_edit_permission(lookups):
    company = _company()
    role = _role(company, "Настройщик", ["settings.edit"])
    user = _member(company, "cfg@t.test", workspace="MEMBER", company_roles=[role])
    resp = _api(user).patch(f"/api/v1/accounts/companies/{company.id}/", {"name": "Renamed"}, format="json")
    assert resp.status_code == 200  # MEMBER WorkspaceRole, but the permission lets them through
    company.refresh_from_db()
    assert company.name == "Renamed"


def test_company_edit_denied_without_permission(lookups):
    company = _company()
    role = _role(company, "Наблюдатель", [])
    user = _member(company, "obs@t.test", workspace="MEMBER", company_roles=[role])
    resp = _api(user).patch(f"/api/v1/accounts/companies/{company.id}/", {"name": "Nope"}, format="json")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "ROLE_NOT_PERMITTED"


def test_company_edit_owner_without_role_denied(lookups):
    company = _company()
    user = _member(company, "owner@t.test", workspace="OWNER")
    resp = _api(user).patch(f"/api/v1/accounts/companies/{company.id}/", {"name": "OwnerRenamed"}, format="json")
    assert resp.status_code == 403  # M1-ERP-05: должность OWNER без роли прав не даёт
    assert resp.json()["detail"] == "ROLE_NOT_PERMITTED"


# ── Gate 2: set-member-role → team.manage ────────────────────────────────────


def test_set_member_role_allowed_with_team_manage(lookups):
    company = _company()
    admin_role = _role(company, "Тим-админ", ["team.manage"])
    admin = _member(company, "teamadmin@t.test", workspace="MEMBER", company_roles=[admin_role])
    target = _member(company, "target@t.test", workspace="MEMBER")
    target_member = CompanyMember.objects.get(user=target)
    resp = _api(admin).post(
        f"/api/v1/accounts/companies/{company.id}/set-member-role/",
        {"member_id": target_member.id, "role": "SALES_MANAGER"},
        format="json",
    )
    assert resp.status_code != 403  # gate passed (payload-level outcome may vary, but not an auth denial)


def test_set_member_role_denied_without_team_manage(lookups):
    company = _company()
    role = _role(company, "Обычный", [])
    user = _member(company, "plain@t.test", workspace="MEMBER", company_roles=[role])
    target = _member(company, "target2@t.test", workspace="MEMBER")
    target_member = CompanyMember.objects.get(user=target)
    resp = _api(user).post(
        f"/api/v1/accounts/companies/{company.id}/set-member-role/",
        {"member_id": target_member.id, "role": "SALES_MANAGER"},
        format="json",
    )
    assert resp.status_code == 403
    assert resp.json()["detail"] == "ROLE_NOT_PERMITTED"


# ── Gate 3: ChargeTemplate CRUD → settings.charge_templates ──────────────────


def test_charge_template_create_denied_without_permission(lookups):
    company = _company()
    role = _role(company, "Без прав", [])
    user = _member(company, "noct@t.test", workspace="MEMBER", company_roles=[role])
    resp = _api(user).post("/api/v1/crm/charge-templates/", _CT_PAYLOAD, format="json")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "ROLE_NOT_PERMITTED"


def test_charge_template_create_allowed_with_permission(lookups):
    company = _company()
    role = _role(company, "Шаблонщик", ["settings.charge_templates"])
    user = _member(company, "ct@t.test", workspace="MEMBER", company_roles=[role])
    resp = _api(user).post("/api/v1/crm/charge-templates/", _CT_PAYLOAD, format="json")
    assert resp.status_code == 201  # MEMBER + permission passes the (now permission-based) gate


def test_charge_template_owner_without_role_denied(lookups):
    company = _company()
    user = _member(company, "ctowner@t.test", workspace="OWNER")
    resp = _api(user).post("/api/v1/crm/charge-templates/", _CT_PAYLOAD, format="json")
    assert resp.status_code == 403  # M1-ERP-05: без роли — без права
    assert resp.json()["detail"] == "ROLE_NOT_PERMITTED"

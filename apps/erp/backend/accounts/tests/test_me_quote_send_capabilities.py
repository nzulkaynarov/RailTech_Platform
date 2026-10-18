"""WP-H — /me.capabilities early-gate signals for the КП builder.

M1-ERP-02 wave 2 removed subscriptions, entitlements and DEMO. The SPA still reads two of the
old signals until its own cleanup, so `/me` keeps them as TRANSITIONAL constants of the seller
side: `can_send_quotes` / `subscription_active` = the user acts for a seller company
(`seller_subscription_operational` = True / None). The DEMO and «blocked by operator»
send flags are gone. UI-gating only — send_to_client (role permission
quote.send) stays authoritative. These tests pin the projection.
"""

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from accounts.serializers import MeSerializer


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})


def _seller_user(email):
    """A SUPPLIER-company OWNER with can_sell."""
    company = Company.objects.create(
        name=f"Seller {email}",
        inn=email,
    )
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user, company


def _caps(user):
    return MeSerializer(user).data["capabilities"]


def test_seller_can_send_without_any_plan(lookups):
    """No subscription exists any more: the seller side always passes the UI send pre-gate;
    the role permission (quote.send) stays authoritative in send_to_client."""
    user, _ = _seller_user("ok@wph.test")
    caps = _caps(user)
    assert "can_send_quotes" not in caps
    assert "subscription_active" not in caps
    assert not [key for key in caps if key.startswith("quote_send_")], "DEMO/operator send flags are gone"
    assert "seller_subscription_operational" not in MeSerializer(user).data


def test_buyer_only_user_has_no_seller_send_signals(lookups):
    company = Company.objects.create(name="Buyer co", inn="buyer@wph.test")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(email="buyer@wph.test", username="buyer@wph.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=False,
    )
    caps = _caps(user)
    assert "can_send_quotes" not in caps
    assert "subscription_active" not in caps
    assert "seller_subscription_operational" not in MeSerializer(user).data


# ──────────────────────────────────────────────────────────────────────────────
# `capabilities.permissions` — действующие права бэк-офиса (M1-ERP-05)
# ──────────────────────────────────────────────────────────────────────────────
#
# Сторона «продавец / покупатель» в `/me` больше не публикуется (`can_sell`/`can_buy` сняты):
# SPA прячет и блокирует интерфейс только по кодам прав — объединению ролей сотрудника своей
# компании. Флаги участника и должность OWNER прав не дают.


def test_member_of_client_only_company_has_no_permissions(lookups):
    company = Company.objects.create(name="Client co", inn="3001000001")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(email="member@caps.test", username="member@caps.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )

    data = MeSerializer(user).data
    assert "can_sell" not in data and "can_buy" not in data
    assert "can_sell" not in data["capabilities"] and "can_buy" not in data["capabilities"]
    assert data["capabilities"]["permissions"] == []


def test_own_staff_without_role_has_no_permissions(lookups):
    """Сотрудник своей компании без роли: флаг `can_sell` и должность OWNER прав не дают."""
    user, _ = _seller_user("seller@caps.test")
    assert MeSerializer(user).data["capabilities"]["permissions"] == []


def test_own_staff_permissions_are_the_union_of_roles(lookups, grant):
    user, _ = _seller_user("nosell@caps.test")
    grant(user, "FULFILLMENT", "data.export")

    permissions = MeSerializer(user).data["capabilities"]["permissions"]
    assert permissions == sorted(["fulfillment.manage", "fulfillment.act", "data.export"])


def test_secondary_own_company_membership_drives_permissions(lookups, grant):
    """Основное членство в компании-покупателе не скрывает права в своей компании."""
    buyer_company = Company.objects.create(name="Buyer primary", inn="3001000003")
    buyer_company.types.add(CompanyType.objects.get(code="CLIENT"))
    seller_company = Company.objects.create(name="Seller secondary", inn="3001000004")
    seller_company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="dual@caps.test", username="dual@caps.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=buyer_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=False,
    )
    CompanyMember.objects.create(
        user=user,
        company=seller_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=False,
        can_sell=True,
    )
    grant(user, "quote.send", company=seller_company)

    assert MeSerializer(user).data["capabilities"]["permissions"] == ["quote.send"]

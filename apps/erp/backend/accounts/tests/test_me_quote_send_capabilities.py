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
        can_buy=True,
    )
    return user, company


def _caps(user):
    return MeSerializer(user).data["capabilities"]


def test_seller_can_send_without_any_plan(lookups):
    """No subscription exists any more: the seller side always passes the UI send pre-gate;
    the role permission (quote.send) stays authoritative in send_to_client."""
    user, _ = _seller_user("ok@wph.test")
    caps = _caps(user)
    assert caps["can_send_quotes"] is True
    assert caps["subscription_active"] is True
    assert not [key for key in caps if key.startswith("quote_send_")], "DEMO/operator send flags are gone"
    assert MeSerializer(user).data["seller_subscription_operational"] is True


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
        can_buy=True,
    )
    caps = _caps(user)
    assert caps["can_send_quotes"] is False
    assert caps["subscription_active"] is False
    assert MeSerializer(user).data["seller_subscription_operational"] is None


# ──────────────────────────────────────────────────────────────────────────────
# `capabilities.can_sell` — «пользователь на стороне продавца» (аудит UI 2026-07-30)
# ──────────────────────────────────────────────────────────────────────────────
#
# Плоский флаг `can_sell` — это CompanyMember.can_sell, и он по умолчанию True у ЛЮБОГО
# участника. Пока `capabilities.can_sell` копировал его, SPA показывала продавцовские
# поверхности (мастер документов с КП/инвойсом, seller-секции настроек) члену чисто
# покупательской компании — и клик уводил в отказ. Теперь поле считает тот же предикат,
# что и авторизация: `is_seller` = сотрудник своей компании (активный участник компании-владельца,
# `core.tenant.own_company_id`; флаг участника сторону больше не выбирает — M1-ERP-02 волна 3).


def test_capability_can_sell_is_false_for_member_of_client_only_company(lookups):
    """Ключевой случай: у участника флаг стоит, но компания не продаёт."""
    company = Company.objects.create(name="Client co", inn="3001000001")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(email="member@caps.test", username="member@caps.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,  # дефолт модели — именно он и вводил интерфейс в заблуждение
        can_buy=True,
    )

    data = MeSerializer(user).data
    assert data["can_sell"] is True, "плоское поле остаётся флагом участника"
    assert data["capabilities"]["can_sell"] is False, "capabilities знает тип компании"


def test_capability_can_sell_is_true_for_seller_company_member(lookups):
    user, _ = _seller_user("seller@caps.test")
    assert MeSerializer(user).data["capabilities"]["can_sell"] is True


def test_capability_can_sell_ignores_the_member_flag_for_own_staff(lookups):
    """Продавец один — своя компания: её сотрудник на стороне продавца, даже если флаг
    участника `can_sell` снят. Что ему МОЖНО, решают права роли, а не сторона."""
    company = Company.objects.create(name="Seller co", inn="3001000002")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="nosell@caps.test", username="nosell@caps.test", password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=False,
        can_buy=True,
    )

    assert MeSerializer(user).data["capabilities"]["can_sell"] is True


def test_capability_can_sell_sees_secondary_seller_membership(lookups):
    """Основное членство в компании-покупателе не должно скрывать продавцовскую сторону."""
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
        can_buy=True,
    )
    CompanyMember.objects.create(
        user=user,
        company=seller_company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=False,
        can_sell=True,
        can_buy=False,
    )

    assert MeSerializer(user).data["capabilities"]["can_sell"] is True

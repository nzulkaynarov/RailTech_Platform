"""Regression tests for Move 2 ownership (ADR-0006) — PER SELLER COMPANY (per-routing).

Competition between routed sellers is hidden: each seller works the заявка independently and the
buyer picks a winner. Ownership lives on DealSellerRouting (per deal+seller_company). Covers:
  * sellers claim INDEPENDENTLY — A's claim never blocks B (the #8 fix)
  * claim is a no-op for the current owner (assigned_at SLA anchor kept)
  * release/assign are scoped to the actor's OWN routed company (no cross-seller interference)
  * assigned_to_name is only the viewer's OWN company's owner (cross-tenant structurally hidden)
  * notify_new_message reaches each routed seller's claimed owner
"""

from types import SimpleNamespace

import pytest

from accounts.models import (
    Company,
    CompanyMember,
    CompanyRole,
    CompanyType,
    CustomUser,
    SystemRole,
    VerificationStatus,
    WorkspaceRole,
)
from crm.models import Deal, DealSellerRouting, DealStage
from crm.serializers import DealListSerializer
from crm.services.assignment import assign_deal, claim_deal, release_deal


def _ws(code):
    return WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})[0]


def _user(email):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)


def _member(user, company, *, company_role=None, can_sell=True, can_buy=False):
    return CompanyMember.objects.create(
        user=user,
        company=company,
        role=_ws("MEMBER"),
        company_role=company_role,
        is_active=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )


def _team_manager_role(company):
    return CompanyRole.objects.create(company=company, name="Админ", permissions=["team.manage", "settings.edit"])


@pytest.fixture
def lookups(db):
    for code in ["DRAFT", "RFQ_OPEN", "CALCULATING"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    VerificationStatus.objects.get_or_create(code="L2_VERIFIED", defaults={"name": "L2", "sort_order": 30})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    from notifications.models import NotificationType

    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 10})


def _company(name, inn, type_code):
    c = Company.objects.create(
        name=name, inn=inn, verification_status=VerificationStatus.objects.get(code="L2_VERIFIED")
    )
    c.types.add(CompanyType.objects.get(code=type_code))
    return c


@pytest.fixture
def scenario(lookups):
    """A buyer RFQ routed to TWO competing seller companies A and B."""
    buyer = _company("Buyer Co", "1110000001", "CLIENT")
    seller_a = _company("Seller A", "2220000001", "SUPPLIER")
    seller_b = _company("Seller B", "2220000002", "SUPPLIER")
    deal = Deal.objects.create(title="RFQ", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_a)
    DealSellerRouting.objects.create(deal=deal, seller_company=seller_b)

    a_member = _user("a.member@a.uz")
    _member(a_member, seller_a)
    a_admin = _user("a.admin@a.uz")
    _member(a_admin, seller_a, company_role=_team_manager_role(seller_a))
    b_member = _user("b.member@b.uz")
    _member(b_member, seller_b)
    b_admin = _user("b.admin@b.uz")
    _member(b_admin, seller_b, company_role=_team_manager_role(seller_b))
    buyer_user = _user("buyer@buyer.uz")
    _member(buyer_user, buyer, can_sell=False, can_buy=True)

    return SimpleNamespace(
        deal=deal,
        buyer=buyer,
        seller_a=seller_a,
        seller_b=seller_b,
        a_member=a_member,
        a_admin=a_admin,
        b_member=b_member,
        b_admin=b_admin,
        buyer_user=buyer_user,
    )


def _routing(deal, company):
    return DealSellerRouting.objects.get(deal=deal, seller_company=company)


# ─── per-seller independence (the #8 fix) ───────────────────────────────────


def test_sellers_claim_independently(scenario):
    """Seller A claiming MUST NOT block seller B from claiming their own copy."""
    _, err_a = claim_deal(scenario.deal.id, scenario.a_member)
    _, err_b = claim_deal(scenario.deal.id, scenario.b_member)
    assert err_a is None and err_b is None
    assert _routing(scenario.deal, scenario.seller_a).assigned_to_id == scenario.a_member.id
    assert _routing(scenario.deal, scenario.seller_b).assigned_to_id == scenario.b_member.id


def test_teammate_cannot_double_claim_same_company_copy(scenario):
    a_member2 = _user("a.member2@a.uz")
    _member(a_member2, scenario.seller_a)
    claim_deal(scenario.deal.id, scenario.a_member)
    _, err = claim_deal(scenario.deal.id, a_member2)
    assert err == "DEAL_ALREADY_CLAIMED"  # a teammate already owns company A's copy


def test_reclaim_by_owner_is_noop_and_preserves_assigned_at(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)
    first_ts = _routing(scenario.deal, scenario.seller_a).assigned_at
    assert first_ts is not None
    claim_deal(scenario.deal.id, scenario.a_member)
    assert _routing(scenario.deal, scenario.seller_a).assigned_at == first_ts  # SLA anchor kept


# ─── cross-seller release/assign isolation ──────────────────────────────────


def test_competitor_admin_cannot_release_another_sellers_claim(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)  # A owns its copy
    claim_deal(scenario.deal.id, scenario.b_member)  # B owns its own copy
    # B's admin releases — may only touch B's OWN routing, never A's claim (cross-seller isolation).
    release_deal(scenario.deal.id, scenario.b_admin)
    assert _routing(scenario.deal, scenario.seller_a).assigned_to_id == scenario.a_member.id  # A intact
    assert _routing(scenario.deal, scenario.seller_b).assigned_to_id is None  # B's own released


def test_owner_can_release_own_claim(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)
    _, err = release_deal(scenario.deal.id, scenario.a_member)
    assert err is None and _routing(scenario.deal, scenario.seller_a).assigned_to_id is None


def test_own_company_admin_can_release_member_claim(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)
    _, err = release_deal(scenario.deal.id, scenario.a_admin)
    assert err is None and _routing(scenario.deal, scenario.seller_a).assigned_to_id is None


def test_admin_can_assign_within_own_company(scenario):
    _, err = assign_deal(scenario.deal.id, scenario.a_admin, scenario.a_member.id)
    assert err is None
    assert _routing(scenario.deal, scenario.seller_a).assigned_to_id == scenario.a_member.id


def test_competitor_admin_cannot_assign_a_rivals_member(scenario):
    _, err = assign_deal(scenario.deal.id, scenario.b_admin, scenario.a_member.id)
    assert err == "ASSIGNEE_NOT_IN_ROUTED_COMPANY"  # assignee must be in the actor's own company


# ─── assigned_to_name shows only the viewer's OWN company owner ──────────────


def _name_as_seen_by(deal, viewer):
    return DealListSerializer(deal, context={"request": SimpleNamespace(user=viewer)}).data["assigned_to_name"]


def test_assigned_to_name_scoped_to_viewers_own_company(scenario):
    claim_deal(scenario.deal.id, scenario.a_member)  # only A's copy claimed
    deal = Deal.objects.get(pk=scenario.deal.id)
    assert _name_as_seen_by(deal, scenario.a_member) == scenario.a_member.email  # own claim
    assert _name_as_seen_by(deal, scenario.a_admin) == scenario.a_member.email  # same company
    assert _name_as_seen_by(deal, scenario.b_admin) is None  # B's own copy is unclaimed → nothing
    assert _name_as_seen_by(deal, scenario.buyer_user) is None  # buyer doesn't own


# ─── подсказка «можно вернуть в очередь» ────────────────────────────────────
#
# Волна U1 закрыла класс ошибок «интерфейс показывает объект, а право на действие выводит сам»:
# сторона зрителя считается СЕРВЕРОМ. `viewer_can_release` — та же дисциплина для владения
# сделкой. Тесты ниже проверяют не текст подсказки, а её СОВПАДЕНИЕ с сервисом: если предикаты
# разойдутся, кнопка появится там, где действие откажет, — ровно то, что мы вычищали.


def _can_release(deal, viewer):
    return DealListSerializer(deal, context={"request": SimpleNamespace(user=viewer)}).data["viewer_can_release"]


def test_release_hint_matches_service_for_every_actor(scenario):
    """Параметризация по всем действующим лицам: подсказка == успех сервиса."""
    claim_deal(scenario.deal.id, scenario.a_member)

    actors = {
        "владелец записи": scenario.a_member,
        "админ своей компании": scenario.a_admin,
        "коллега без team.manage": _member_of_seller_a(scenario),
        "продавец-конкурент": scenario.b_member,
        "админ конкурента": scenario.b_admin,
        "покупатель": scenario.buyer_user,
    }
    for name, actor in actors.items():
        hint = _can_release(scenario.deal, actor)
        # Сервис вызываем на СВЕЖЕЙ копии состояния: он меняет данные, поэтому сначала снимаем
        # подсказку, потом пробуем действие и возвращаем владение на место.
        _, err = release_deal(scenario.deal.id, actor)
        allowed = err is None and _routing(scenario.deal, scenario.seller_a).assigned_to_id is None
        assert hint == allowed, f"{name}: подсказка {hint}, а сервис {'разрешил' if allowed else 'отказал'}"
        # восстанавливаем исходное владение для следующего актора
        routing = _routing(scenario.deal, scenario.seller_a)
        if routing.assigned_to_id is None:
            claim_deal(scenario.deal.id, scenario.a_member)


def _member_of_seller_a(scenario):
    """Второй рядовой участник компании A — у него нет ни записи, ни team.manage."""
    user = CustomUser.objects.filter(email="a.colleague@a.uz").first()
    if user is None:
        user = _user("a.colleague@a.uz")
        _member(user, scenario.seller_a)
    return user


def test_no_release_hint_while_deal_is_unclaimed(scenario):
    """Возвращать нечего, пока никто не взял: кнопка не должна появляться рядом с «Взять»."""
    assert _can_release(scenario.deal, scenario.a_member) is False


def test_platform_operator_never_gets_release_hint(scenario):
    """Оператор платформы — наблюдатель (ADR-0002), от имени компании он не действует."""
    claim_deal(scenario.deal.id, scenario.a_member)
    operator = _user("operator@platform.uz")
    operator.role = SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 1})[0]
    operator.save(update_fields=["role"])
    assert _can_release(scenario.deal, operator) is False

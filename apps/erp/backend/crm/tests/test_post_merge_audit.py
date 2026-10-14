"""Regression tests for Move 2 ownership (ADR-0006) — the back-office work-queue.

The seller of every deal is the own company (BUSINESS §3.3, M1-ERP-02 wave 3), so a заявка has ONE
owner — `Deal.assigned_to` (+ `assigned_at`, the time-to-first-touch SLA anchor). Covers:
  * a staff member claims; a teammate cannot double-claim; re-claim by the owner is a no-op
  * release: the owner or a `team.manage` admin; a plain colleague, the buyer, an outsider cannot
  * assign: a `team.manage` admin to a colleague of the own company, never to an outsider
  * `assigned_to_name` / `viewer_can_release` hints computed by the server match the services
"""

from types import SimpleNamespace

import pytest

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, SystemRole, WorkspaceRole
from crm.models import Deal, DealStage
from crm.serializers import DealListSerializer
from crm.services.assignment import assign_deal, claim_deal, release_deal


def _ws(code):
    return WorkspaceRole.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})[0]


def _user(email):
    return CustomUser.objects.create_user(email=email, username=email, password="pw", is_active=True)


def _member(user, company, *, company_roles=(), can_sell=True, can_buy=False):
    return CompanyMember.objects.create(
        user=user,
        company=company,
        role=_ws("MEMBER"),
        company_roles=list(company_roles),
        is_active=True,
        can_sell=can_sell,
        can_buy=can_buy,
    )


def _team_manager_role(company):
    # Распределение очереди — право `deal.assign` (M1-ERP-05; до него — team.manage).
    return CompanyRole.objects.create(
        company=company, name="Админ", permissions=["team.manage", "settings.edit", "deal.assign"]
    )


@pytest.fixture
def lookups(db):
    for code in ["DRAFT", "RFQ_OPEN", "CALCULATING"]:
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    SystemRole.objects.get_or_create(code="USER", defaults={"name": "User", "sort_order": 10})
    from notifications.models import NotificationType

    NotificationType.objects.get_or_create(code="INFO", defaults={"name": "Info", "sort_order": 10})


def _company(name, inn, type_code):
    c = Company.objects.create(name=name, inn=inn)
    c.types.add(CompanyType.objects.get(code=type_code))
    return c


@pytest.fixture
def scenario(lookups):
    """A buyer RFQ in the back-office queue; the own company's team; an outsider."""
    buyer = _company("Buyer Co", "1110000001", "CLIENT")
    own = _company("Own Co", "2220000001", "SUPPLIER")
    other_client = _company("Other Client", "1110000002", "CLIENT")
    deal = Deal.objects.create(title="RFQ", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))

    member = _user("member@own.uz")
    _member(member, own)
    admin = _user("admin@own.uz")
    _member(admin, own, company_roles=[_team_manager_role(own)])
    colleague = _user("colleague@own.uz")
    _member(colleague, own)
    buyer_user = _user("buyer@buyer.uz")
    _member(buyer_user, buyer, can_sell=False, can_buy=True)
    outsider = _user("outsider@other.uz")
    _member(outsider, other_client, company_roles=[_team_manager_role(other_client)])

    return SimpleNamespace(
        deal=deal,
        member=member,
        admin=admin,
        colleague=colleague,
        buyer_user=buyer_user,
        outsider=outsider,
    )


def _owner_id(deal):
    return Deal.objects.values_list("assigned_to_id", flat=True).get(pk=deal.pk)


# ─── claim ──────────────────────────────────────────────────────────────────


def test_staff_claims_the_deal(scenario):
    _, err = claim_deal(scenario.deal.id, scenario.member)
    assert err is None
    assert _owner_id(scenario.deal) == scenario.member.id


def test_teammate_cannot_double_claim(scenario):
    claim_deal(scenario.deal.id, scenario.member)
    _, err = claim_deal(scenario.deal.id, scenario.colleague)
    assert err == "DEAL_ALREADY_CLAIMED"  # a teammate already owns it
    assert _owner_id(scenario.deal) == scenario.member.id


def test_reclaim_by_owner_is_noop_and_preserves_assigned_at(scenario):
    claim_deal(scenario.deal.id, scenario.member)
    first_ts = Deal.objects.get(pk=scenario.deal.pk).assigned_at
    assert first_ts is not None
    claim_deal(scenario.deal.id, scenario.member)
    assert Deal.objects.get(pk=scenario.deal.pk).assigned_at == first_ts  # SLA anchor kept


@pytest.mark.parametrize("actor", ["buyer_user", "outsider"])
def test_non_staff_cannot_claim(scenario, actor):
    _, err = claim_deal(scenario.deal.id, getattr(scenario, actor))
    assert err == "MEMBER_REQUIRED_FOR_ACTION"
    assert _owner_id(scenario.deal) is None


# ─── release / assign ───────────────────────────────────────────────────────


def test_owner_can_release_own_claim(scenario):
    claim_deal(scenario.deal.id, scenario.member)
    _, err = release_deal(scenario.deal.id, scenario.member)
    assert err is None and _owner_id(scenario.deal) is None


def test_team_admin_can_release_member_claim(scenario):
    claim_deal(scenario.deal.id, scenario.member)
    _, err = release_deal(scenario.deal.id, scenario.admin)
    assert err is None and _owner_id(scenario.deal) is None


def test_colleague_without_deal_assign_cannot_release(scenario):
    claim_deal(scenario.deal.id, scenario.member)
    _, err = release_deal(scenario.deal.id, scenario.colleague)
    assert err == "MEMBER_REQUIRED_FOR_ACTION"
    assert _owner_id(scenario.deal) == scenario.member.id


def test_outsider_admin_cannot_release(scenario):
    """`deal.assign` in ANOTHER company gives nothing over the back-office queue."""
    claim_deal(scenario.deal.id, scenario.member)
    _, err = release_deal(scenario.deal.id, scenario.outsider)
    assert err is not None
    assert _owner_id(scenario.deal) == scenario.member.id


def test_admin_can_assign_within_own_company(scenario):
    _, err = assign_deal(scenario.deal.id, scenario.admin, scenario.member.id)
    assert err is None
    assert _owner_id(scenario.deal) == scenario.member.id


def test_admin_cannot_assign_to_an_outsider(scenario):
    _, err = assign_deal(scenario.deal.id, scenario.admin, scenario.buyer_user.id)
    assert err == "ASSIGNEE_NOT_IN_OWN_COMPANY"
    assert _owner_id(scenario.deal) is None


def test_plain_member_cannot_assign(scenario):
    _, err = assign_deal(scenario.deal.id, scenario.colleague, scenario.member.id)
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


def test_outsider_admin_cannot_assign(scenario):
    _, err = assign_deal(scenario.deal.id, scenario.outsider, scenario.member.id)
    assert err == "MEMBER_REQUIRED_FOR_ACTION"


# ─── assigned_to_name — the deal owner, the same for every viewer ───────────


def _name_as_seen_by(deal, viewer):
    return DealListSerializer(deal, context={"request": SimpleNamespace(user=viewer)}).data["assigned_to_name"]


def test_assigned_to_name_is_the_deal_owner(scenario):
    claim_deal(scenario.deal.id, scenario.member)
    deal = Deal.objects.get(pk=scenario.deal.id)
    assert _name_as_seen_by(deal, scenario.member) == scenario.member.email
    assert _name_as_seen_by(deal, scenario.admin) == scenario.member.email


# ─── подсказка «можно вернуть в очередь» ────────────────────────────────────
#
# Волна U1 закрыла класс ошибок «интерфейс показывает объект, а право на действие выводит сам»:
# сторона зрителя считается СЕРВЕРОМ. `viewer_can_release` — та же дисциплина для владения
# сделкой. Тесты ниже проверяют не текст подсказки, а её СОВПАДЕНИЕ с сервисом.


def _can_release(deal, viewer):
    deal = Deal.objects.get(pk=deal.pk)
    return DealListSerializer(deal, context={"request": SimpleNamespace(user=viewer)}).data["viewer_can_release"]


def test_release_hint_matches_service_for_every_actor(scenario):
    """Параметризация по всем действующим лицам: подсказка == успех сервиса."""
    claim_deal(scenario.deal.id, scenario.member)

    actors = {
        "владелец записи": scenario.member,
        "админ своей компании": scenario.admin,
        "коллега без deal.assign": scenario.colleague,
        "посторонний админ": scenario.outsider,
        "покупатель": scenario.buyer_user,
    }
    for name, actor in actors.items():
        hint = _can_release(scenario.deal, actor)
        _, err = release_deal(scenario.deal.id, actor)
        allowed = err is None and _owner_id(scenario.deal) is None
        assert hint == allowed, f"{name}: подсказка {hint}, а сервис {'разрешил' if allowed else 'отказал'}"
        # восстанавливаем исходное владение для следующего актора
        if _owner_id(scenario.deal) is None:
            claim_deal(scenario.deal.id, scenario.member)


def test_no_release_hint_while_deal_is_unclaimed(scenario):
    """Возвращать нечего, пока никто не взял: кнопка не должна появляться рядом с «Взять»."""
    assert _can_release(scenario.deal, scenario.member) is False


def test_platform_operator_never_gets_release_hint(scenario):
    """Бывший оператор платформы (SystemRole ADMIN без is_superuser) от имени компании не действует."""
    claim_deal(scenario.deal.id, scenario.member)
    operator = _user("operator@platform.uz")
    operator.role = SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 1})[0]
    operator.save(update_fields=["role"])
    assert _can_release(scenario.deal, operator) is False

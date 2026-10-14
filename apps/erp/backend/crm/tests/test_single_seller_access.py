"""Продавец один — компания-владелец (BUSINESS §3.3, M1-ERP-02 волна 3).

Маршрутизация заявки между продавцами удалена. Граница доступа теперь такая:

* сотрудник своей компании (активный участник `core.tenant.own_company_id`) видит ВСЕ сделки
  ERP — любой компании-клиента и черновики без клиента; что он может менять, решают права роли
  (`member_has_permission`): роль без прав («Наблюдатель») видит, но не двигает сделку и не
  правит КП;
* посторонний (не участник, деактивированный участник) не видит ничего;
* покупательский аккаунт (до M2-ERP-01) — только сделки своей компании-клиента.

Здесь же — разрешение «своей компании»: настройка `OWN_COMPANY_ID` важнее вывода, вывод берёт
единственную компанию-продавца с активными участниками, неоднозначность — ошибка конфигурации.
"""

from decimal import Decimal

import pytest
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, WorkspaceRole
from core.tenant import own_company, own_company_id
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus

MANAGER_PERMISSIONS = ["deal.manage", "quote.build", "quote.edit_pricing", "quote.view_cost_margin"]


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="MEMBER", defaults={"name": "Member", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    for code, order in (("DRAFT", 10), ("RFQ_OPEN", 20), ("SOURCING", 25), ("CALCULATING", 30)):
        DealStage.objects.get_or_create(code=code, defaults={"name": code, "sort_order": order})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})


def _company(name, inn, type_code):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code=type_code))
    return company


def _member(company, email, *, permissions=None, is_active=True, **flags):
    user = CustomUser.objects.create_user(email=email, username=email, password="x", is_active=True)
    role = None
    if permissions is not None:
        role = CompanyRole.objects.create(company=company, name=f"role {email}", permissions=permissions)
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="MEMBER"),
        company_roles=[role],
        is_active=is_active,
        is_primary=True,
        **flags,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _ids(response):
    body = response.json()
    rows = body["results"] if isinstance(body, dict) and "results" in body else body
    return {row["id"] for row in rows}


def _quote(deal, preparer):
    return Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        prepared_by=preparer,
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )


@pytest.fixture
def world(lookups):
    own = _company("Own Co", "S100", "SUPPLIER")
    client_a = _company("Client A", "C100", "CLIENT")
    client_b = _company("Client B", "C200", "CLIENT")
    rfq_open = DealStage.objects.get(code="RFQ_OPEN")
    return {
        "own": own,
        "client_a": client_a,
        "client_b": client_b,
        "manager": _member(own, "manager@own.test", permissions=MANAGER_PERMISSIONS),
        "observer": _member(own, "observer@own.test", permissions=[]),
        "former": _member(own, "former@own.test", permissions=MANAGER_PERMISSIONS, is_active=False),
        "buyer_a": _member(client_a, "buyer@a.test", can_buy=True),
        "outsider": CustomUser.objects.create_user(email="out@x.test", username="out@x.test", password="x"),
        "deal_a": Deal.objects.create(title="A", company=client_a, stage=rfq_open),
        "deal_b": Deal.objects.create(title="B", company=client_b, stage=rfq_open),
        "draft": Deal.objects.create(title="calc", company=None, stage=DealStage.objects.get(code="DRAFT")),
    }


# ── «своя компания» ─────────────────────────────────────────────────────────


def test_own_company_is_the_single_seller_company_with_members(world):
    assert own_company_id() == world["own"].id
    assert own_company() == world["own"]


def test_member_less_seller_company_does_not_compete_for_own(world):
    # Поставщик из каталога (компания-продавец без участников) — контрагент, а не «своя компания».
    _company("Catalog Supplier", "S200", "SUPPLIER")
    assert own_company_id() == world["own"].id


def test_two_seller_companies_with_members_need_explicit_setting(world, settings):
    rival = _company("Second Seller", "S300", "SUPPLIER")
    _member(rival, "staff@second.test", permissions=MANAGER_PERMISSIONS)
    with pytest.raises(ImproperlyConfigured):
        own_company_id()
    settings.OWN_COMPANY_ID = world["own"].id
    assert own_company_id() == world["own"].id


def test_setting_wins_over_inference(world, settings):
    other = _company("Configured Co", "S400", "SUPPLIER")
    settings.OWN_COMPANY_ID = other.id
    assert own_company_id() == other.id
    # Сотрудник «выведенной» компании больше не сотрудник: продавец — настроенная компания.
    assert _ids(_api(world["manager"]).get("/api/v1/crm/deals/")) == set()


def test_no_staff_yet_means_no_own_company(lookups):
    _company("Fresh Co", "S500", "SUPPLIER")
    assert own_company_id() is None


# ── видимость сделок ────────────────────────────────────────────────────────


def test_staff_with_permission_sees_all_deals_of_own_company(world):
    visible = _ids(_api(world["manager"]).get("/api/v1/crm/deals/"))
    assert {world["deal_a"].id, world["deal_b"].id, world["draft"].id} <= visible


def test_staff_without_permission_sees_deals_but_cannot_move_them(world):
    observer = _api(world["observer"])
    assert {world["deal_a"].id, world["deal_b"].id} <= _ids(observer.get("/api/v1/crm/deals/"))
    assert observer.get(f"/api/v1/crm/deals/{world['deal_a'].id}/").status_code == 200

    denied = observer.post(
        f"/api/v1/crm/deals/{world['deal_a'].id}/change-stage/", {"stage_code": "CALCULATING"}, format="json"
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "ROLE_NOT_PERMITTED"
    world["deal_a"].refresh_from_db()
    assert world["deal_a"].stage.code == "RFQ_OPEN"

    allowed = _api(world["manager"]).post(
        f"/api/v1/crm/deals/{world['deal_a'].id}/change-stage/", {"stage_code": "CALCULATING"}, format="json"
    )
    assert allowed.status_code == 200, allowed.content
    world["deal_a"].refresh_from_db()
    assert world["deal_a"].stage.code == "CALCULATING"


def test_staff_without_permission_cannot_edit_the_quote(world):
    item = QuoteItem.objects.create(quote=_quote(world["deal_a"], world["manager"]), imported_raw_name="X", quantity=1)
    denied = _api(world["observer"]).patch(
        f"/api/v1/crm/quote-items/{item.id}/", {"frozen_base_price": "1"}, format="json"
    )
    assert denied.status_code == 403
    # M1-ERP-05: без права роли отказывает гейт эндпоинта (до сервиса) единым кодом.
    assert denied.json()["detail"] == "ROLE_NOT_PERMITTED"


@pytest.mark.parametrize("who", ["former", "outsider"])
def test_non_staff_sees_no_deal(world, who):
    api = _api(world[who])
    assert _ids(api.get("/api/v1/crm/deals/")) == set()
    assert api.get(f"/api/v1/crm/deals/{world['deal_a'].id}/").status_code == 404
    assert api.get(f"/api/v1/crm/deals/{world['draft'].id}/").status_code == 404


def test_buyer_account_sees_only_own_company_deals(world):
    visible = _ids(_api(world["buyer_a"]).get("/api/v1/crm/deals/"))
    assert visible == {world["deal_a"].id}


def test_viewer_side_is_staff_for_every_deal(world):
    rows = _api(world["manager"]).get("/api/v1/crm/deals/").json()
    rows = rows["results"] if isinstance(rows, dict) else rows
    assert rows and all(row["viewer_is_seller"] for row in rows)
    assert all("target_sellers_data" not in row for row in rows)


# ── КП: тот же продавец для любой заявки ────────────────────────────────────


def test_staff_can_price_buyer_prepared_quote(world):
    """Regression (prod $224-instead-of-$68k bug): строки заявки покупателя и КП — ОДИН и тот же
    Quote, созданный ПОКУПАТЕЛЕМ (prepared_by=buyer). Сотрудник своей компании обязан его оценить;
    роль без права цены — нет."""
    quote = _quote(world["deal_a"], world["buyer_a"])
    item = QuoteItem.objects.create(quote=quote, imported_raw_name="Рельс Р65", quantity=10)

    resp = _api(world["manager"]).patch(
        f"/api/v1/crm/quote-items/{item.id}/",
        {"frozen_base_price": "500", "margin_percent": "20", "quantity": "10"},
        format="json",
    )
    assert resp.status_code == 200, resp.content
    quote.refresh_from_db()
    assert quote.subtotal_excl_vat > 0


def test_quote_items_filter_scopes_to_requested_deal(world):
    """DRF silent-filter contract: `?quote__deal_id=<A>` возвращает ТОЛЬКО строки сделки A, хотя
    сотрудник видит обе сделки (неизвестный фильтр не должен молча отдавать «всё»)."""
    item_a = QuoteItem.objects.create(
        quote=_quote(world["deal_a"], world["manager"]), imported_raw_name="A", quantity=1
    )
    item_b = QuoteItem.objects.create(
        quote=_quote(world["deal_b"], world["manager"]), imported_raw_name="B", quantity=1
    )

    resp = _api(world["manager"]).get(f"/api/v1/crm/quote-items/?quote__deal_id={world['deal_a'].id}")
    assert resp.status_code == 200, resp.content
    ids = _ids(resp)
    assert item_a.id in ids
    assert item_b.id not in ids


def test_quote_is_anchored_to_own_company(world):
    resp = _api(world["manager"]).post(
        "/api/v1/crm/quotes/", {"deal": world["deal_b"].id, "vat_rate": "12"}, format="json"
    )
    assert resp.status_code == 201, resp.content
    quote = Quote.objects.get(pk=resp.json()["id"])
    assert quote.seller_company_id == world["own"].id
    assert quote.prepared_by_id == world["manager"].id

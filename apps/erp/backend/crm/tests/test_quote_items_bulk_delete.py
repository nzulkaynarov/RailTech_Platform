"""Транзакционное массовое удаление строк КП.

Раньше фронт слал N ПАРАЛЛЕЛЬНЫХ DELETE (bulk-эндпоинта не было). Каждый запрос брал блокировку
строки КП и пересчитывал каскад, поэтому четыре одновременных удаления стабильно ловили
`deadlock detected` в Postgres: часть строк исчезала, часть оставалась, а продавец видел только
«Operation failed» и не знал, что именно удалилось. Найдено прогоном глазами 19-08.

POST /api/v1/crm/quote-items/bulk-delete/ — ВСЁ ИЛИ НИЧЕГО: одна транзакция, одна блокировка КП,
ОДИН пересчёт. Брат-близнец `test_quote_items_bulk_create.py` / `_update.py` по гардам.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from accounts.services.roles import ensure_default_company_roles
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus
from master_data.models import Currency

BULK_URL = "/api/v1/crm/quote-items/bulk-delete/"


@pytest.fixture
def lookups(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})
    DealStage.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Draft", "sort_order": 10})
    SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 10})
    Currency.objects.get_or_create(code="UZS", defaults={"name": "Узбекский сум", "sort_order": 10})


def _seller(name, inn, email):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
        company_roles=[ensure_default_company_roles(company)["HEAD"]],
    )
    return user, company


def _outsider(email):
    """A member of ANOTHER (client) company — legacy OWNER there, but not own-company staff."""
    company = Company.objects.create(name=f"Other {email}", inn=email[:12])
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    user = CustomUser.objects.create_user(email=email, username=email, password="x")
    CompanyMember.objects.create(
        user=user,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
        can_sell=True,
    )
    return user


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _quote_with_items(buyer_co, seller_co, count=4):
    deal = Deal.objects.create(title="КП", company=buyer_co, stage=DealStage.objects.get(code="DRAFT"))
    quote = Quote.objects.create(
        deal=deal,
        version=1,
        status=QuoteStatus.objects.get(code="DRAFT"),
        vat_rate=Decimal("12"),
        subtotal_excl_vat=Decimal("0"),
        vat_amount=Decimal("0"),
        total_incl_vat=Decimal("0"),
    )
    items = [
        QuoteItem.objects.create(
            quote=quote,
            imported_raw_name=f"Позиция {index}",
            quantity=Decimal("1"),
            frozen_base_price=Decimal("100"),
            position=index,
        )
        for index in range(1, count + 1)
    ]
    return quote, items


@pytest.fixture
def world(lookups):
    seller_user, seller_co = _seller("Seller A", "A100", "sa-del@t.test")
    buyer_co = Company.objects.create(name="Buyer Co", inn="C100")
    buyer_co.types.add(CompanyType.objects.get(code="CLIENT"))
    return dict(seller_user=seller_user, seller_co=seller_co, buyer_co=buyer_co)


@pytest.mark.django_db
def test_bulk_delete_removes_all_and_recalculates_once(world):
    """Четыре строки уходят ОДНИМ запросом, каскад пересчитывается РОВНО один раз."""
    quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], count=4)
    ids = [item.id for item in items]

    from crm.services.quotes import QuoteCalculationService

    with patch.object(
        QuoteCalculationService,
        "recalculate_quote",
        side_effect=QuoteCalculationService.recalculate_quote,
    ) as spy:
        resp = _api(world["seller_user"]).post(BULK_URL, {"quote": quote.id, "items": ids}, format="json")

    assert resp.status_code == 200, resp.data
    assert sorted(resp.data["deleted"]) == sorted(ids)
    assert QuoteItem.objects.filter(quote=quote).count() == 0
    assert spy.call_count == 1, "пересчёт должен быть ОДИН на всю пачку, а не по строке"


@pytest.mark.django_db
def test_foreign_item_rejects_whole_batch(world):
    """Чужая строка не «пропускается молча» — не удаляется НИЧЕГО, и продавец узнаёт причину."""
    quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], count=3)
    other_quote, other_items = _quote_with_items(world["buyer_co"], world["seller_co"], count=1)
    ids = [items[0].id, other_items[0].id]

    resp = _api(world["seller_user"]).post(BULK_URL, {"quote": quote.id, "items": ids}, format="json")

    assert resp.status_code == 400
    assert resp.data["detail"] == "QUOTE_ITEMS_BULK_INVALID"
    assert resp.data["rows"][0]["id"] == other_items[0].id
    assert QuoteItem.objects.filter(quote=quote).count() == 3, "batch должен был откатиться целиком"
    assert QuoteItem.objects.filter(quote=other_quote).count() == 1


@pytest.mark.django_db
def test_frozen_quote_rejected(world):
    """Замороженное (отправленное) КП строк не теряет — это уже документ у клиента."""
    from django.utils import timezone

    quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], count=2)
    quote.frozen_at = timezone.now()
    quote.save(update_fields=["frozen_at"])

    resp = _api(world["seller_user"]).post(BULK_URL, {"quote": quote.id, "items": [items[0].id]}, format="json")

    assert resp.status_code == 400
    assert resp.data["detail"] == "QUOTE_FROZEN"
    assert QuoteItem.objects.filter(quote=quote).count() == 2


@pytest.mark.django_db
def test_outsider_is_refused(world, lookups):
    """Посторонний (участник другой компании) не может удалять строки КП бэк-офиса."""
    stranger = _outsider("sb-del@t.test")
    quote, items = _quote_with_items(world["buyer_co"], world["seller_co"], count=2)

    resp = _api(stranger).post(BULK_URL, {"quote": quote.id, "items": [items[0].id]}, format="json")

    assert resp.status_code == 403
    assert resp.json()["detail"] == "ROLE_NOT_PERMITTED"  # гейт роли (M1-ERP-05)
    assert QuoteItem.objects.filter(quote=quote).count() == 2


@pytest.mark.django_db
def test_empty_list_rejected(world):
    quote, _items = _quote_with_items(world["buyer_co"], world["seller_co"], count=1)
    resp = _api(world["seller_user"]).post(BULK_URL, {"quote": quote.id, "items": []}, format="json")
    assert resp.status_code == 400
    assert resp.data["detail"] == "QUOTE_ITEMS_BULK_EMPTY"

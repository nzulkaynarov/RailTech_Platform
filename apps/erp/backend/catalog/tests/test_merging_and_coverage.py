"""Слияние дублей и метрика покрытия каталога (волны B и C).

Дубли неизбежны по построению: карточка у каждого продавца своя, а позиция приходит из заявок
под разными именами, и точный ключ (артикул/ГОСТ) есть не всегда. Автоматически такие карточки
не склеиваются — ложное слияние стоит дороже дубля. Эталон (Akeneo, Pimcore, Salesforce,
HubSpot): система предлагает, человек решает; выжившую запись выбирает пользователь.

Покрытие меряется в СТРОКАХ КП, а не в числе карточек: каталог из тысячи неиспользуемых
карточек не стоит ничего. Так же считает Ariba (catalog spend, а не размер каталога).
"""

from decimal import Decimal

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.coverage import catalog_coverage
from catalog.merging import merge_products
from catalog.models import Product, ProductStatus, StockStatus, SupplierOffer
from crm.models import Deal, Quote, QuoteItem, QuoteStatus
from master_data.models import Currency

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(db, grant):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован"), ("ARCHIVED", "В архиве")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    seller = Company.objects.create(name="ООО Слияние", inn="9500000001")
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="m@merge.test", username="m@merge.test", password="pw")
    CompanyMember.objects.create(
        user=user, company=seller, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    grant(user, "HEAD")  # M1-ERP-05: права сотрудника — только из ролей
    return {"seller": seller, "user": user}


def _card(world, name, **kwargs):
    return Product.objects.create(name=name, owner_company=world["seller"], **kwargs)


def test_merge_keeps_knowledge_from_both_cards(world):
    """Слияние обязано ДОБАВЛЯТЬ знание, а не терять его."""
    survivor = _card(world, "Подшипник буксовый 30-232726Е2М", hs_code="8482100000")
    duplicate = _card(world, "Подшипник 232726 (буксовый узел)", gost_drawing="ГОСТ 520-2011")

    merged, error = merge_products(survivor, duplicate, world["user"])

    assert error is None
    assert merged.hs_code == "8482100000", "своё не затирается"
    assert merged.gost_drawing == "ГОСТ 520-2011", "чужое дозаполняет пустое"


def test_demand_is_summed_not_lost(world):
    """Спрос — накопленная статистика очереди наполнения; при слиянии она складывается."""
    survivor = _card(world, "Скрепление КБ-65", demand_count=3)
    duplicate = _card(world, "Скрепление рельсовое КБ-65", demand_count=5)

    merged, _error = merge_products(survivor, duplicate, world["user"])

    assert merged.demand_count == 8


def test_offers_and_quote_lines_follow_the_survivor(world):
    """Иначе оффер и строка КП остались бы висеть на архивной карточке."""
    survivor = _card(world, "Рельс Р65")
    duplicate = _card(world, "Рельс Р-65")
    currency, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Сум", "sort_order": 10})
    stock, _ = StockStatus.objects.get_or_create(code="IN_STOCK", defaults={"name": "В наличии", "sort_order": 10})
    offer = SupplierOffer.objects.create(
        product=duplicate, supplier=world["seller"], base_price=Decimal("100"), currency=currency, stock_status=stock
    )
    deal = Deal.objects.create(title="Сделка M", company=world["seller"])
    quote = Quote.objects.create(deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"))
    line = QuoteItem.objects.create(quote=quote, position=1, quantity=1, product=duplicate)

    merge_products(survivor, duplicate, world["user"])

    offer.refresh_from_db()
    line.refresh_from_db()
    assert offer.product_id == survivor.pk
    assert line.product_id == survivor.pk


def test_duplicate_is_archived_never_deleted(world):
    """На поглощённую карточку могут ссылаться исторические документы — удалять историю нельзя."""
    survivor = _card(world, "Клапан 4300")
    duplicate = _card(world, "Клапан концевой 4300")

    merge_products(survivor, duplicate, world["user"])

    duplicate.refresh_from_db()
    assert duplicate.status.code == "ARCHIVED"
    assert Product.objects.filter(pk=duplicate.pk).exists()


def test_a_seller_cannot_merge_across_companies(world):
    """Сводить карточки РАЗНЫХ продавцов в мастер-запись может только платформа."""
    survivor = _card(world, "Тормозная колодка")
    rival = Company.objects.create(name="ООО Чужая", inn="9500000002")
    theirs = Product.objects.create(name="Колодка тормозная", owner_company=rival)

    merged, error = merge_products(survivor, theirs, world["user"])

    assert merged is None and error in ("PRODUCT_NOT_YOURS", "MERGE_CROSS_COMPANY_FORBIDDEN")


def test_coverage_counts_quote_lines_not_cards(world):
    """Каталог из тысячи неиспользуемых карточек не стоит ничего — меряем строки КП."""
    card = _card(world, "Рельс Р65", status=ProductStatus.objects.get(code="PUBLISHED"))
    deal = Deal.objects.create(title="Сделка C", company=world["seller"])
    quote = Quote.objects.create(
        deal=deal, version=1, status=QuoteStatus.objects.get(code="DRAFT"), seller_company=world["seller"]
    )
    QuoteItem.objects.create(quote=quote, position=1, quantity=1, product=card)
    QuoteItem.objects.create(quote=quote, position=2, quantity=1, imported_raw_name="Позиция вне каталога")

    report = catalog_coverage(world["seller"])

    assert report["lines_total"] == 2
    assert report["lines_with_product"] == 1
    assert report["percent"] == 50

"""Публикует ВЛАДЕЛЕЦ карточки, а порог держит вычисляемая полнота.

До волны A публиковать мог только платформенный оператор (`bulk_publish` под `IsPlatformAdmin`):
продавец не мог выпустить в каталог даже собственный товар, и каталог не наполнялся. Эталон
обратный — Amazon Business, Alibaba, Shopify: публикует владелец, площадка модерирует
пост-фактум. Роль проверяющего играет детерминированный порог (Akeneo completeness), а не
человек.
"""

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.completeness import completeness
from catalog.models import Category, DomainType, Product, ProductStatus
from catalog.publishing import publish_many, publish_product
from master_data.models import UnitOfMeasure

pytestmark = pytest.mark.django_db


@pytest.fixture
def seller_world(db):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    # Публикация требует только права `catalog.publish` и полноты карточки: верификации
    # компании (KYC) больше нет — M1-ERP-02 волна 1c.
    company = Company.objects.create(
        name="ООО Издатель",
        inn="9300000001",
    )
    user = CustomUser.objects.create_user(email="own@pub.test", username="own@pub.test", password="pw")
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    uom, _ = UnitOfMeasure.objects.get_or_create(code="H87", defaults={"name": "шт.", "sort_order": 10})
    domain, _ = DomainType.objects.get_or_create(
        code="GENERAL_GOODS", defaults={"name": "Общие товары", "sku_prefix": "GG", "sort_order": 20}
    )
    category, _ = Category.objects.get_or_create(name="Крепёж", defaults={"domain_type": domain})
    return {"company": company, "user": user, "uom": uom, "domain": domain, "category": category}


def _card(world, **kwargs):
    defaults = {
        "name": "Скрепление КБ-65",
        "owner_company": world["company"],
        "status": ProductStatus.objects.get(code="DRAFT"),
    }
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


def test_incomplete_card_cannot_be_published_and_the_error_names_what_is_missing(seller_world):
    card = _card(seller_world)

    published, error = publish_product(card, seller_world["user"])

    assert published is None
    assert error.startswith("PRODUCT_INCOMPLETE:")
    # Пользователь не должен гадать — код перечисляет недостающее (линия E2 с блоками шаблона).
    assert "category" in error and "uom" in error


def test_owner_publishes_once_the_card_is_complete(seller_world):
    card = _card(
        seller_world,
        domain_type=seller_world["domain"],
        uom=seller_world["uom"],
        category=seller_world["category"],
        hs_code="7302300000",
    )
    assert completeness(card)["is_publishable"] is True

    published, error = publish_product(card, seller_world["user"])

    assert error is None
    assert published.status.code == "PUBLISHED"


def test_a_stranger_cannot_publish_someone_elses_card(seller_world):
    card = _card(
        seller_world,
        domain_type=seller_world["domain"],
        uom=seller_world["uom"],
        category=seller_world["category"],
        hs_code="7302300000",
    )
    stranger = CustomUser.objects.create_user(email="x@pub.test", username="x@pub.test", password="pw")

    published, error = publish_product(card, stranger)

    assert published is None and error == "PRODUCT_NOT_YOURS"


def test_bulk_publish_reports_line_by_line(seller_world):
    """Частичный успех честнее отказа всей пачки — так же отчитываются Akeneo и Shopify."""
    complete = _card(
        seller_world,
        domain_type=seller_world["domain"],
        uom=seller_world["uom"],
        category=seller_world["category"],
        hs_code="7302300000",
    )
    incomplete = _card(seller_world, name="Полуфабрикат")

    report = publish_many([complete.pk, incomplete.pk], seller_world["user"])

    assert report["published"] == [complete.pk]
    assert len(report["skipped"]) == 1
    assert report["skipped"][0]["id"] == incomplete.pk


def test_requirements_depend_on_the_domain(seller_world):
    """У услуги не бывает ни артикула, ни ТН ВЭД — требовать их значит запереть каталог."""
    services, _ = DomainType.objects.get_or_create(
        code="SERVICES", defaults={"name": "Услуги", "sku_prefix": "SV", "sort_order": 30}
    )
    service_category, _ = Category.objects.get_or_create(name="Монтаж", defaults={"domain_type": services})
    card = _card(
        seller_world,
        name="Шефмонтаж стрелочного перевода",
        domain_type=services,
        uom=seller_world["uom"],
        category=service_category,
    )

    assert completeness(card)["is_publishable"] is True, "услуге хватает имени, единицы и категории"

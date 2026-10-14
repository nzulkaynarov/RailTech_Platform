"""R2 — жизненный цикл карточки: снятие с витрины, обратимый архив, происхождение.

До этой волны публикация была улицей с односторонним движением: выпустить карточку продавец
мог, а снять — нет; архив был чёрной дырой — слитый дубль уходил в ARCHIVED и исчезал из всех
вкладок без пути назад. Эталон Shopify: Active → Draft двусторонне, Archive — отдельное и
ОБРАТИМОЕ действие (unarchive → Draft).
"""

import pytest
from rest_framework.test import APIClient

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.merging import merge_products
from catalog.models import Category, DomainType, Product, ProductStatus
from catalog.publishing import archive_many, archive_product, publish_product, restore_product, unpublish_product
from crm.models import Deal, DealStage
from master_data.models import UnitOfMeasure

pytestmark = pytest.mark.django_db

PRODUCTS_URL = "/api/v1/catalog/products/"


@pytest.fixture
def world(db, settings, grant):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован"), ("ARCHIVED", "Архив")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    owner_role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "Открытый RFQ", "sort_order": 25})
    uom, _ = UnitOfMeasure.objects.get_or_create(code="H87", defaults={"name": "шт.", "sort_order": 10})
    domain, _ = DomainType.objects.get_or_create(
        code="GENERAL_GOODS", defaults={"name": "Общие товары", "sku_prefix": "GG", "sort_order": 20}
    )
    category, _ = Category.objects.get_or_create(name="Крепёж", defaults={"domain_type": domain})

    seller = Company.objects.create(
        name="ООО Витрина",
        inn="9600000001",
    )
    seller.types.add(CompanyType.objects.get(code="SUPPLIER"))
    seller_user = CustomUser.objects.create_user(email="own@r2.test", username="own@r2.test", password="pw")
    CompanyMember.objects.create(
        user=seller_user, company=seller, role=owner_role, is_active=True, is_primary=True, can_sell=True
    )
    settings.OWN_COMPANY_ID = seller.id  # своя компания; «чужая» ниже — не сотрудники (M1-ERP-05)
    grant(seller_user, "CATALOG_SUPPLY")  # права сотрудника — только из ролей

    # Чужая компания — для PRODUCT_NOT_YOURS и смеси в bulk_archive.
    other = Company.objects.create(name="ООО Чужие", inn="9600000003")
    other.types.add(CompanyType.objects.get(code="SUPPLIER"))
    stranger = CustomUser.objects.create_user(email="stranger@r2.test", username="stranger@r2.test", password="pw")
    CompanyMember.objects.create(
        user=stranger, company=other, role=owner_role, is_active=True, is_primary=True, can_sell=True
    )

    buyer = Company.objects.create(name="ООО Покупатель Р2", inn="9600000004")
    deal = Deal.objects.create(title="Заявка Р2", company=buyer, stage=DealStage.objects.get(code="RFQ_OPEN"))

    client = APIClient()
    client.force_authenticate(seller_user)

    return {
        "seller": seller,
        "seller_user": seller_user,
        "other": other,
        "stranger": stranger,
        "deal": deal,
        "uom": uom,
        "domain": domain,
        "category": category,
        "client": client,
    }


def _card(world, *, company=None, status_code="DRAFT", **kwargs):
    defaults = {
        "name": "Скрепление КБ-65",
        "owner_company": company or world["seller"],
        "status": ProductStatus.objects.get(code=status_code),
    }
    defaults.update(kwargs)
    return Product.objects.create(**defaults)


def _complete_kwargs(world):
    """Поля, при которых карточке для публикации не хватает только решения владельца."""
    return {
        "domain_type": world["domain"],
        "uom": world["uom"],
        "category": world["category"],
        "hs_code": "7318159000",
        "description": "Описание для клиента",  # M1-ERP-07: порог требует описание или характеристики
    }


# ── Снятие с витрины (Shopify: Active → Draft двусторонне) ───────────────────────────────


def test_owner_unpublishes_a_published_card(world):
    card = _card(world, status_code="PUBLISHED")

    unpublished, error = unpublish_product(card, world["seller_user"])

    assert error is None
    card.refresh_from_db()
    assert card.status.code == "DRAFT", "снятая карточка возвращается в черновики, а не исчезает"
    assert unpublished.pk == card.pk


def test_a_stranger_cannot_unpublish_someone_elses_card(world):
    card = _card(world, status_code="PUBLISHED")

    unpublished, error = unpublish_product(card, world["stranger"])

    assert unpublished is None and error == "PRODUCT_NOT_YOURS"
    card.refresh_from_db()
    assert card.status.code == "PUBLISHED", "статус не должен меняться при отказе"


def test_unpublish_requires_a_published_card(world):
    card = _card(world, status_code="DRAFT")

    unpublished, error = unpublish_product(card, world["seller_user"])

    assert unpublished is None and error == "PRODUCT_NOT_PUBLISHED"


# ── Архив: отдельное и обратимое действие ────────────────────────────────────────────────


def test_archive_and_restore_cycle(world):
    card = _card(world)

    _, error = archive_product(card, world["seller_user"])
    assert error is None
    card.refresh_from_db()
    assert card.status.code == "ARCHIVED"

    _, error = restore_product(card, world["seller_user"])
    assert error is None
    card.refresh_from_db()
    assert card.status.code == "DRAFT", "возврат — в черновики: витрину карточка заслуживает заново"


def test_archiving_twice_reports_already_archived(world):
    card = _card(world, status_code="ARCHIVED")

    archived, error = archive_product(card, world["seller_user"])

    assert archived is None and error == "PRODUCT_ALREADY_ARCHIVED"


def test_restore_refuses_a_card_that_is_not_archived(world):
    card = _card(world, status_code="DRAFT")

    restored, error = restore_product(card, world["seller_user"])

    assert restored is None and error == "PRODUCT_NOT_ARCHIVED"


# ── Публикация, снятие и архив — по правам роли, без верификации компании ───────────────


def test_seller_publishes_unpublishes_and_archives_its_own_cards(world):
    """KYC удалён (M1-ERP-02 волна 1c): своя компания публикует полную карточку, снимает её с
    витрины и убирает в архив по правам роли («Каталог и закупки») — без порога верификации."""
    published = _card(world, status_code="PUBLISHED", **_complete_kwargs(world))

    draft = _card(world, **_complete_kwargs(world))
    _, publish_error = publish_product(draft, world["seller_user"])
    assert publish_error is None
    draft.refresh_from_db()
    assert draft.status.code == "PUBLISHED"

    _, error = unpublish_product(published, world["seller_user"])
    assert error is None
    published.refresh_from_db()
    assert published.status.code == "DRAFT"

    _, error = archive_product(published, world["seller_user"])
    assert error is None
    published.refresh_from_db()
    assert published.status.code == "ARCHIVED"


# ── Пакетный архив: построчный отчёт ─────────────────────────────────────────────────────


def test_bulk_archive_reports_line_by_line_on_a_mixed_batch(world):
    mine = _card(world)
    someone_elses = _card(world, company=world["other"], name="Чужая карточка")

    report = archive_many([mine.pk, someone_elses.pk], world["seller_user"])

    assert report["archived"] == [mine.pk]
    assert report["skipped"] == [{"product_id": someone_elses.pk, "error": "PRODUCT_NOT_YOURS"}]
    someone_elses.refresh_from_db()
    assert someone_elses.status.code == "DRAFT", "чужая карточка не тронута"


# ── Происхождение: табы «Кандидаты из заявок» vs «Черновики» (аудит §5.2) ────────────────


def _names(response):
    return {row["name"] for row in response.json()["results"]}


def test_origin_splits_rfq_candidates_from_manual_drafts(world):
    _card(world, name="Спрошенная из КП", demand_count=2)
    _card(world, name="Рождённая из заявки", source_deal=world["deal"])
    _card(world, name="Заведена руками")

    rfq = _names(world["client"].get(PRODUCTS_URL, {"mine": "1", "origin": "rfq"}))
    manual = _names(world["client"].get(PRODUCTS_URL, {"mine": "1", "origin": "manual"}))
    all_drafts = _names(world["client"].get(PRODUCTS_URL, {"mine": "1", "status": "DRAFT"}))

    assert rfq == {"Спрошенная из КП", "Рождённая из заявки"}
    assert manual == {"Заведена руками"}
    assert rfq | manual == all_drafts, "табы обязаны покрывать реестр без потерь и пересечений"
    assert rfq & manual == set()


def test_unknown_origin_value_is_silently_ignored(world):
    _card(world, name="Единственная")

    rows = _names(world["client"].get(PRODUCTS_URL, {"mine": "1", "origin": "weird"}))

    assert rows == {"Единственная"}


# ── Архив перестал быть чёрной дырой: слитый дубль виден и восстановим ───────────────────


def test_merged_duplicate_is_visible_in_the_archive_tab_and_restorable(world):
    survivor = _card(world, name="Подшипник буксовый 30-232726Е2М")
    duplicate = _card(world, name="Подшипник 232726 (буксовый узел)")

    merged, error = merge_products(survivor, duplicate, world["seller_user"])
    assert error is None and merged.pk == survivor.pk
    duplicate.refresh_from_db()
    assert duplicate.status.code == "ARCHIVED", "слитый дубль уходит в архив, не удаляется"

    archived_tab = world["client"].get(PRODUCTS_URL, {"mine": "1", "status": "ARCHIVED"})
    assert duplicate.pk in {row["id"] for row in archived_tab.json()["results"]}

    response = world["client"].post(f"{PRODUCTS_URL}{duplicate.pk}/restore/")
    assert response.status_code == 200
    duplicate.refresh_from_db()
    assert duplicate.status.code == "DRAFT", "путь назад существует — архив больше не чёрная дыра"

"""Наполнять каталог можно до верификации, публиковать — нет.

Эталон Amazon Seller Central: пока идёт проверка аккаунта, продавец готовит листинги, а живыми
они становятся после неё. У нас до этой волны всё было наоборот — `kyc: true` прятал раздел
«Номенклатура» целиком, и новый продавец простаивал ровно в тот момент, когда готов работать:
ни карточку завести, ни прайс загрузить, пока оператор не посмотрит документы.

Гейт не добавлен, а ПЕРЕЕХАЛ с раздела на само действие. Прав стало строго больше: всё, что
работало до волны, работает и после.
"""

import pytest

from accounts.models import (
    Company,
    CompanyMember,
    CompanyType,
    CustomUser,
    VerificationStatus,
    WorkspaceRole,
)
from catalog.completeness import completeness
from catalog.models import Category, DomainType, Product, ProductStatus
from catalog.publishing import publish_many, publish_product
from master_data.models import UnitOfMeasure

pytestmark = pytest.mark.django_db


def _company(name: str, inn: str, *, verified: bool) -> Company:
    status = VerificationStatus.objects.get(code="L2_VERIFIED") if verified else None
    return Company.objects.create(name=name, inn=inn, verification_status=status)


@pytest.fixture
def world(db):
    for code, name in (("DRAFT", "Черновик"), ("PUBLISHED", "Опубликован")):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": name, "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    owner_role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    uom, _ = UnitOfMeasure.objects.get_or_create(code="H87", defaults={"name": "шт.", "sort_order": 10})
    domain, _ = DomainType.objects.get_or_create(
        code="GENERAL_GOODS", defaults={"name": "Общие товары", "sku_prefix": "GG", "sort_order": 20}
    )
    category, _ = Category.objects.get_or_create(name="Крепёж", defaults={"domain_type": domain})

    pending = _company("ООО На проверке", "9500000001", verified=False)
    pending_user = CustomUser.objects.create_user(email="pending@kyc.test", username="pending@kyc.test", password="pw")
    CompanyMember.objects.create(
        user=pending_user, company=pending, role=owner_role, is_active=True, is_primary=True, can_sell=True
    )

    verified = _company("ООО Проверенный", "9500000002", verified=True)
    verified_user = CustomUser.objects.create_user(
        email="verified@kyc.test", username="verified@kyc.test", password="pw"
    )
    CompanyMember.objects.create(
        user=verified_user, company=verified, role=owner_role, is_active=True, is_primary=True, can_sell=True
    )

    return {
        "pending": pending,
        "pending_user": pending_user,
        "verified": verified,
        "verified_user": verified_user,
        "uom": uom,
        "domain": domain,
        "category": category,
    }


def _complete_card(world, company) -> Product:
    """Карточка, которой для публикации не хватает ТОЛЬКО верификации владельца."""
    card = Product.objects.create(
        name="Скрепление КБ-65",
        owner_company=company,
        status=ProductStatus.objects.get(code="DRAFT"),
        domain_type=world["domain"],
        category=world["category"],
        uom=world["uom"],
        hs_code="7318159000",
    )
    assert completeness(card)["is_publishable"], "фикстура обязана быть полной, иначе тест меряет не то"
    return card


# ── Наполнение открыто ───────────────────────────────────────────────────────────────────


def test_unverified_seller_can_create_a_card(world):
    """Главное обещание волны: карточка заводится, пока идёт проверка документов."""
    card = Product.objects.create(
        name="Позиция до верификации",
        owner_company=world["pending"],
        status=ProductStatus.objects.get(code="DRAFT"),
    )

    assert card.pk is not None
    assert card.status.code == "DRAFT"


def test_unverified_seller_sees_what_is_missing_for_publication(world):
    """Полнота считается и до верификации — иначе наполнять было бы вслепую."""
    card = _complete_card(world, world["pending"])

    assert completeness(card)["is_publishable"] is True


# ── Публикация закрыта ───────────────────────────────────────────────────────────────────


def test_unverified_seller_cannot_publish(world):
    card = _complete_card(world, world["pending"])

    published, error = publish_product(card, world["pending_user"])

    assert published is None
    assert error == "SELLER_KYC_REQUIRED"
    card.refresh_from_db()
    assert card.status.code == "DRAFT", "статус не должен измениться при отказе"


def test_verified_seller_publishes_the_same_card(world):
    """Контроль: дело именно в верификации, а не в данных карточки."""
    card = _complete_card(world, world["verified"])

    published, error = publish_product(card, world["verified_user"])

    assert error is None
    assert published is not None
    card.refresh_from_db()
    assert card.status.code == "PUBLISHED"


def test_kyc_is_checked_before_completeness(world):
    """Порядок кодов важен: чинить категорию, чтобы упереться в KYC, — тупик.

    Канон проекта тот же на отправке КП: `SELLER_KYC_REQUIRED` идёт раньше остальных отказов.
    """
    card = Product.objects.create(
        name="Неполная карточка непроверенного",
        owner_company=world["pending"],
        status=ProductStatus.objects.get(code="DRAFT"),
    )
    assert not completeness(card)["is_publishable"]

    _, error = publish_product(card, world["pending_user"])

    assert error == "SELLER_KYC_REQUIRED", "иначе продавец сначала правит поля, потом всё равно упирается"


def test_bulk_publish_refuses_the_unverified_owner_line_by_line(world):
    mine = _complete_card(world, world["pending"])

    report = publish_many([mine.pk], world["pending_user"])

    assert report["published"] == []
    assert [row["error"] for row in report["skipped"]] == ["SELLER_KYC_REQUIRED"]

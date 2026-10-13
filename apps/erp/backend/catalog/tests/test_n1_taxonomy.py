"""N1 (spec-nomenclature-audit-2026-08-04) — данные и корень «заблокированных» селектов.

Аудит показал: таксономия платформы была ПУСТА (Category=0, EquipmentGroup=0, Manufacturer=0
на проде), домен задвоен (GENERAL из миграции против GENERAL_GOODS из dev-сида), и продавец
упирался в обязательные поля, наполнить которые не мог. Канон: таксономию поставляет
платформа (Amazon browse tree), пустой справочник не блокирует (перенос канона ТН ВЭД),
бренд — нормализуемый ввод продавца (Odoo create-on-the-fly).
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.completeness import completeness
from catalog.models import Category, DomainType, EquipmentGroup, Manufacturer, Product, ProductStatus
from catalog.services import find_or_create_manufacturer

pytestmark = pytest.mark.django_db


@pytest.fixture
def seller_client(db):
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    company = Company.objects.create(name="ООО Н1", inn="9500000001")
    company.types.add(supplier_type)
    user = CustomUser.objects.create_user(email="n1@seller.test", username="n1@seller.test", password="pw")
    CompanyMember.objects.create(user=user, company=company, role=role, is_active=True, is_primary=True)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def test_general_domain_is_merged_into_general_goods():
    """Дубль «Общие товары»/«Общие промышленные товары» больше не виден пользователю."""
    codes = dict(DomainType.objects.values_list("code", "is_active"))
    assert codes.get("GENERAL_GOODS") is True
    # GENERAL либо отсутствует (свежая база), либо деактивирован (существующая).
    assert codes.get("GENERAL") in (None, False)


def test_starter_taxonomy_is_seeded_by_migration():
    """После migrate на ПУСТОЙ базе продавцу есть из чего выбирать (Rule 1)."""
    railway = DomainType.objects.get(code="RAILWAY_MACHINERY")
    assert Category.objects.filter(domain_type=railway).exists()
    assert Category.objects.filter(domain_type__code="SERVICES").exists()
    deep_group = EquipmentGroup.objects.filter(name="Тепловозы").first()
    assert deep_group is not None
    assert deep_group.cached_path == "Подвижной состав / Локомотивы / Тепловозы"


def test_empty_equipment_classifier_does_not_block_railway_card(seller_client):
    """Канон ТН ВЭД: пустой справочник → требование выключено, карточка сохраняется."""
    EquipmentGroup.objects.all().delete()
    railway = DomainType.objects.get(code="RAILWAY_MACHINERY")

    response = seller_client.post(
        "/api/v1/catalog/products/",
        {"name": "Ось колёсной пары", "domain_type": railway.pk, "equipment_groups": []},
        format="json",
    )

    assert response.status_code == 201, response.content
    card = Product.objects.get(pk=response.json()["id"])
    assert "equipment_groups" not in [item["code"] for item in completeness(card)["missing"]]


def test_filled_classifier_still_requires_a_group(seller_client):
    """С наполненным справочником прежнее правило действует — API отвечает чистым 400."""
    railway = DomainType.objects.get(code="RAILWAY_MACHINERY")

    response = seller_client.post(
        "/api/v1/catalog/products/",
        {"name": "Ось колёсной пары", "domain_type": railway.pk, "equipment_groups": []},
        format="json",
    )

    assert response.status_code == 400
    assert "equipment_groups" in response.json()


def test_brand_name_creates_and_reuses_manufacturer(seller_client):
    """Бренд на лету: строка из формы → запись справочника; регистр не плодит дубли."""
    first = seller_client.post(
        "/api/v1/catalog/products/", {"name": "Подшипник", "brand_name": "SKF Group"}, format="json"
    )
    second = seller_client.post(
        "/api/v1/catalog/products/", {"name": "Подшипник 2", "brand_name": "skf group"}, format="json"
    )

    assert first.status_code == 201, first.content
    assert second.status_code == 201, second.content
    assert Manufacturer.objects.filter(name__iexact="skf group").count() == 1
    brands = {Product.objects.get(pk=r.json()["id"]).brand_id for r in (first, second)}
    assert len(brands) == 1 and None not in brands


def test_blank_brand_name_clears_the_brand(seller_client):
    brand = find_or_create_manufacturer("Siemens")
    card = Product.objects.create(name="Реле", brand=brand, owner_company=Company.objects.get(inn="9500000001"))

    response = seller_client.patch(f"/api/v1/catalog/products/{card.pk}/", {"brand_name": ""}, format="json")

    assert response.status_code == 200, response.content
    card.refresh_from_db()
    assert card.brand_id is None

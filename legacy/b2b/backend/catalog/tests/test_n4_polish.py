"""N4 (spec-nomenclature-audit-2026-08-04) — доводка направления «Номенклатура».

Смерженные, но не подключённые механики получают путь к пользователю: подсказки дублей
(Akeneo/Salesforce: система предлагает, человек решает) и метрика покрытия; цифровой запрос
несуществующего кода ТН ВЭД деградирует к ветке максимального префикса, а не в текстовый мусор.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.hs_suggest import suggest_hs_codes
from catalog.merging import duplicate_suggestions
from catalog.models import Product, ProductStatus
from master_data.models import HSCode

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(db):
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    ProductStatus.objects.get_or_create(code="ARCHIVED", defaults={"name": "Архив", "sort_order": 30})
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    company = Company.objects.create(name="ООО Н4", inn="9200000001")
    company.types.add(supplier_type)
    user = CustomUser.objects.create_user(email="n4@seller.test", username="n4@seller.test", password="pw")
    CompanyMember.objects.create(user=user, company=company, role=role, is_active=True, is_primary=True)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return {"company": company, "client": client}


def test_duplicate_suggestions_group_by_exact_keys_only(world):
    """Группировка по точным ключам; «похожие» имена НЕ склеиваются (ложное слияние дороже дубля)."""
    company = world["company"]
    old = Product.objects.create(name="Подшипник 232726", owner_company=company, gost_drawing="ГОСТ 520-2011")
    Product.objects.create(name="Подшипник буксовый 232726", owner_company=company, gost_drawing="гост 520-2011")
    Product.objects.create(name="Подшипник шариковый", owner_company=company)  # одиночка

    groups = duplicate_suggestions(company)

    assert len(groups) == 1
    assert groups[0]["survivor"]["id"] == old.pk, "выжившая — старейшая карточка"
    assert len(groups[0]["duplicates"]) == 1


def test_duplicate_suggestions_ignore_other_companies(world):
    rival = Company.objects.create(name="ООО Чужие", inn="9200000002")
    Product.objects.create(name="Один и тот же ГОСТ", owner_company=world["company"], gost_drawing="Г-1")
    Product.objects.create(name="Один и тот же ГОСТ", owner_company=rival, gost_drawing="Г-1")

    assert duplicate_suggestions(world["company"]) == []


def test_duplicate_suggestions_endpoint_requires_seller(world):
    outsider = CustomUser.objects.create_user(email="out@n4.test", username="out@n4.test", password="pw")
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(outsider).access_token}")

    assert client.get("/api/v1/catalog/products/duplicate-suggestions/").status_code == 403
    assert world["client"].get("/api/v1/catalog/products/duplicate-suggestions/").status_code == 200


def test_digit_query_degrades_to_longest_prefix_branch(world):
    """Несуществующий 10-значный код → ветка максимального префикса, а не текстовый мусор."""
    HSCode.objects.create(code="730210", name="Рельсы", level=6)
    HSCode.objects.create(code="7302101000", name="Рельсы:токоведущие", level=10)

    rows = suggest_hs_codes("7302100000", limit=5)

    assert rows, "деградация к префиксу обязана вернуть ветку"
    assert all(row["code"].startswith("730210") for row in rows)


def test_digit_query_with_no_branch_returns_empty_not_text_noise(world):
    HSCode.objects.create(code="730210", name="Рельсы", level=6)

    assert suggest_hs_codes("99999999", limit=5) == []

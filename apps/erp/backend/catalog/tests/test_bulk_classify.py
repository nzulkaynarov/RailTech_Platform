"""T4 — пакетная классификация: предложения с подтверждением, никогда молча.

Паттерн Avalara/Zonos: AI классифицирует каталог пакетом, но у каждой классификации есть
подтверждающий человек. Применение — отдельный шаг `hs-apply`, и он принимает только коды,
существующие в справочнике.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.hs_lookup_ai import classify_products
from catalog.models import Product, ProductStatus
from crm.models import ActivityLog
from master_data.models import HSCode

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(db, grant):
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    HSCode.objects.create(code="848210", name="Подшипники шариковые", level=6)
    HSCode.objects.create(code="8482100000", name="Подшипники шариковые прочие", level=10)
    company = Company.objects.create(name="ООО Классификация", inn="9700000001")
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    user = CustomUser.objects.create_user(email="c@bulk.test", username="c@bulk.test", password="pw")
    CompanyMember.objects.create(
        user=user, company=company, role=WorkspaceRole.objects.get(code="OWNER"), is_active=True, is_primary=True
    )
    grant(user, "HEAD")  # M1-ERP-05: права сотрудника — только из ролей
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return {"company": company, "user": user, "client": client}


def test_classification_suggests_without_touching_cards(world, settings):
    """Пакет возвращает ПРЕДЛОЖЕНИЯ; карточка не меняется, пока человек не подтвердил."""
    settings.AI_IMPORT_ENABLED = False  # детерминированный фолбэк: лучший retrieval-кандидат
    card = Product.objects.create(name="Подшипники шариковые", owner_company=world["company"])

    outcome = classify_products([card.pk])

    row = outcome["results"][0]
    assert row["suggested_code"].startswith("8482")
    card.refresh_from_db()
    assert card.hs_code == "", "предложение не применяется молча"


def test_apply_writes_the_code_and_leaves_an_ai_provenance_trail(world):
    card = Product.objects.create(name="Подшипник", owner_company=world["company"])

    response = world["client"].post(
        "/api/v1/catalog/products/hs-apply/",
        {"assignments": [{"product_id": card.pk, "code": "8482 10 0000"}]},
        format="json",
    )

    assert response.status_code == 200, response.content
    assert response.json()["applied"] == [card.pk]
    card.refresh_from_db()
    assert card.hs_code == "8482100000"
    trail = ActivityLog.objects.get(event_code="product.hs_code_changed")
    assert trail.event_params["origin"] == "ai"


def test_apply_rejects_codes_outside_the_classifier(world):
    """Даже подтверждённый человеком код обязан существовать — опечатка не проходит."""
    card = Product.objects.create(name="Деталь", owner_company=world["company"])

    response = world["client"].post(
        "/api/v1/catalog/products/hs-apply/",
        {"assignments": [{"product_id": card.pk, "code": "9999999999"}]},
        format="json",
    )

    body = response.json()
    assert body["applied"] == []
    assert body["skipped"][0]["reason"] == "HS_CODE_UNKNOWN"


def test_apply_refuses_someone_elses_card(world):
    rival = Company.objects.create(name="ООО Чужая", inn="9700000002")
    theirs = Product.objects.create(name="Чужая деталь", owner_company=rival)

    response = world["client"].post(
        "/api/v1/catalog/products/hs-apply/",
        {"assignments": [{"product_id": theirs.pk, "code": "8482100000"}]},
        format="json",
    )

    assert response.json()["skipped"][0]["reason"] == "PRODUCT_NOT_YOURS"
    theirs.refresh_from_db()
    assert theirs.hs_code == ""


def test_classify_endpoint_filters_foreign_cards_before_the_paid_job(world):
    """Чужие карточки выбрасываются ДО постановки платной задачи, а не внутри неё."""
    rival = Company.objects.create(name="ООО Соперник", inn="9700000003")
    theirs = Product.objects.create(name="Соперника деталь", owner_company=rival)

    response = world["client"].post(
        "/api/v1/catalog/products/hs-classify/",
        {"product_ids": [theirs.pk]},
        format="json",
    )

    assert response.status_code == 403

"""N3 (spec-nomenclature-audit-2026-08-04) — слой прав каталога стал действующим.

До N3: `catalog.manage`/`catalog.publish` только прятали пункт меню («Наблюдатель» не видел
«Номенклатуру», но правил и публиковал карточки прямым API); любая суб-роль оператора —
включая SUPPORT «только просмотр» — удаляла товары и перекраивала дерево категорий;
операторские карточки рождались «ничьими»; `hs_lookup`/`hs_classify` звали LLM без гейта,
в отличие от enrich на той же странице. С M1-ERP-02 (волна 2) гейт у всех трёх — право роли
`catalog.manage`, а не платный план.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, SystemRole, WorkspaceRole
from catalog.models import Product, ProductStatus

pytestmark = pytest.mark.django_db


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture
def world(db):
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    sales_role, _ = WorkspaceRole.objects.get_or_create(
        code="SALES_MANAGER", defaults={"name": "Менеджер", "sort_order": 20}
    )
    company = Company.objects.create(name="ООО Н3", inn="9300000001")
    company.types.add(supplier_type)
    card = Product.objects.create(name="Карточка Н3", owner_company=company)
    return {"company": company, "card": card, "workspace_role": sales_role}


def _member(world, email, permissions):
    role = CompanyRole.objects.create(company=world["company"], name=f"Роль {email}", permissions=permissions)
    user = CustomUser.objects.create_user(email=email, username=email, password="pw")
    CompanyMember.objects.create(
        user=user,
        company=world["company"],
        role=world["workspace_role"],
        company_roles=[role],
        is_active=True,
        is_primary=True,
    )
    return user


def test_member_without_catalog_manage_cannot_edit_by_api(world):
    """«Наблюдатель» не видит меню — и теперь не может править по прямому API тоже."""
    observer = _member(world, "observer@n3.test", [])

    response = _client_for(observer).patch(
        f"/api/v1/catalog/products/{world['card'].pk}/", {"name": "Взлом"}, format="json"
    )

    assert response.status_code == 403


def test_member_with_catalog_manage_edits_fine(world):
    manager = _member(world, "manager@n3.test", ["catalog.manage"])

    response = _client_for(manager).patch(
        f"/api/v1/catalog/products/{world['card'].pk}/", {"name": "Правка менеджера"}, format="json"
    )

    assert response.status_code == 200, response.content


def test_publish_requires_catalog_publish_not_just_manage(world):
    """Наполнять карточку и выпускать её в каталог — разные способности."""
    from catalog.publishing import publish_product

    manager = _member(world, "manage-only@n3.test", ["catalog.manage"])
    publisher = _member(world, "publisher@n3.test", ["catalog.manage", "catalog.publish"])

    _card, manage_error = publish_product(world["card"], manager)
    assert manage_error == "PRODUCT_NOT_YOURS"

    # Публикатору мешает только полнота карточки — права уже достаточно.
    _card, publish_error = publish_product(world["card"], publisher)
    assert publish_error != "PRODUCT_NOT_YOURS"


def test_operator_card_requires_owner_company(world):
    """Оператор не может родить «ничью» карточку — её никогда не заберёт продавец."""
    admin_role, _ = SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Администратор"})
    operator = CustomUser.objects.create_user(
        is_superuser=True, email="operator@n3.test", username="operator@n3.test", password="pw", role=admin_role
    )
    client = _client_for(operator)

    ownerless = client.post("/api/v1/catalog/products/", {"name": "Ничья"}, format="json")
    owned = client.post(
        "/api/v1/catalog/products/", {"name": "Своя", "owner_company": world["company"].pk}, format="json"
    )

    assert ownerless.status_code == 400
    assert "OWNER_COMPANY_REQUIRED" in ownerless.content.decode()
    assert owned.status_code == 201, owned.content
    assert Product.objects.get(pk=owned.json()["id"]).owner_company_id == world["company"].pk


def test_hs_lookup_is_role_gated(world):
    """LLM-подбор кода — под тем же гейтом, что enrich: право роли `catalog.manage`."""
    viewer = _member(world, "viewer@n3.test", [])

    response = _client_for(viewer).post(
        "/api/v1/catalog/products/hs-lookup/", {"description": "прокладка под рельс"}, format="json"
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "ROLE_NOT_PERMITTED"


def test_hs_lookup_is_open_to_a_catalog_manager_without_any_plan(world, settings, monkeypatch):
    """Платного плана больше нет: ведущий каталог доходит до постановки задачи."""
    from types import SimpleNamespace

    settings.AI_IMPORT_ENABLED = True
    monkeypatch.setattr(
        "sourcing.tasks_ai.run_ai_job.apply_async",
        lambda args=None, task_id=None, **kw: SimpleNamespace(id=task_id),
    )
    seller = _member(world, "no-plan@n3.test", ["catalog.manage"])

    response = _client_for(seller).post(
        "/api/v1/catalog/products/hs-lookup/", {"description": "прокладка под рельс"}, format="json"
    )

    assert response.status_code == 202, response.content

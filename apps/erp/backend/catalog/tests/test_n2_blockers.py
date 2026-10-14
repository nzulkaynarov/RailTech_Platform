"""N2 (spec-nomenclature-audit-2026-08-04) — блокеры формы и публикации.

B4: `status` был записываемым полем сериализатора — продавец публиковал PATCH'ем в обход
порога полноты `publish_product()` («порог считается, а не назначается» — Akeneo). Теперь
статус меняют только сервисы жизненного цикла.

M1: DRF игнорировал `?page_size=` (не был настроен `page_size_query_param`) — очередь
номенклатуры всегда резалась на 20 строк, 21-й кандидат был недостижим.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, WorkspaceRole
from catalog.models import Product, ProductStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def seller(db, grant):
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликован", "sort_order": 20})
    supplier_type, _ = CompanyType.objects.get_or_create(
        code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20}
    )
    role, _ = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    # Тесты N2 проверяют блокеры формы и публикации.
    company = Company.objects.create(
        name="ООО Н2",
        inn="9400000001",
    )
    company.types.add(supplier_type)
    user = CustomUser.objects.create_user(email="n2@seller.test", username="n2@seller.test", password="pw")
    CompanyMember.objects.create(user=user, company=company, role=role, is_active=True, is_primary=True)
    grant(user, "HEAD")  # M1-ERP-05: права сотрудника — только из ролей
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return {"client": client, "company": company}


def test_status_cannot_be_published_by_patch(seller):
    """B4: прямой PATCH статуса игнорируется — публикация только через сервис с полнотой."""
    card = Product.objects.create(name="Неполная карточка", owner_company=seller["company"])
    published_id = ProductStatus.objects.get(code="PUBLISHED").pk

    response = seller["client"].patch(f"/api/v1/catalog/products/{card.pk}/", {"status": published_id}, format="json")

    assert response.status_code == 200, response.content
    card.refresh_from_db()
    assert card.status.code == "DRAFT", "status — read-only: жизненный цикл меняют только сервисы"


def test_publish_action_still_flips_the_status(seller):
    """Служебный путь публикации работает как раньше (полная карточка — для чистоты условия)."""
    from catalog.publishing import publish_product
    from master_data.models import UnitOfMeasure

    uom, _ = UnitOfMeasure.objects.get_or_create(code="PCS", defaults={"name": "шт", "sort_order": 10})
    services_domain_card = Product.objects.create(name="Услуга доставки", owner_company=seller["company"], uom=uom)
    # Домен SERVICES: требования — имя, вид, ед.изм., категория, описание, политика исполнения.
    from catalog.models import Category, DomainType

    services = DomainType.objects.get(code="SERVICES")
    services_domain_card.domain_type = services
    services_domain_card.category = Category.objects.filter(domain_type=services).first()
    # M1-ERP-07: услуге нужны описание и политика исполнения.
    services_domain_card.description = "Доставка до склада клиента"
    services_domain_card.fulfillment_policy = "fixed"
    services_domain_card.save()

    member = CustomUser.objects.get(email="n2@seller.test")
    published, error = publish_product(services_domain_card, member)

    assert error is None
    assert published.status.code == "PUBLISHED"


def test_page_size_query_param_is_honoured_and_capped(seller):
    """M1: `?page_size=` работает; выше потолка 200 — обрезается, а не 500."""
    for index in range(25):
        Product.objects.create(name=f"Позиция {index}", owner_company=seller["company"])

    default = seller["client"].get("/api/v1/catalog/products/?mine=1")
    widened = seller["client"].get("/api/v1/catalog/products/?mine=1&page_size=200")
    absurd = seller["client"].get("/api/v1/catalog/products/?mine=1&page_size=99999")

    assert len(default.json()["results"]) == 20
    assert len(widened.json()["results"]) == 25
    assert absurd.status_code == 200
    assert len(absurd.json()["results"]) == 25

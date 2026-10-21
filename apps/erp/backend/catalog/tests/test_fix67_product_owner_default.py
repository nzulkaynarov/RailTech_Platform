"""FIX-67: товар, заведённый через форму, принадлежит своей компании без выбора владельца.

Дефект прода: `POST /api/v1/catalog/products/` от администратора отвечал 400 `OWNER_COMPANY_REQUIRED` — форма
поле «компания-владелец» не показывает, а сервер требовал его у суперпользователя. ERP не маркетплейс (BUSINESS §3.3):
владелец карточки — своя компания (`core.tenant.own_company`), как у любой сделки, КП и счёта. Явно названная
компания по-прежнему главнее; если свою компанию определить нельзя — прежний отказ, а не «ничья» карточка (N3).
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyRole, CompanyType, CustomUser, SystemRole, WorkspaceRole
from catalog.models import Product, ProductStatus

pytestmark = pytest.mark.django_db

URL = "/api/v1/catalog/products/"


def _client_for(user) -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


@pytest.fixture(autouse=True)
def lookups():
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})
    CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Поставщик", "sort_order": 20})
    WorkspaceRole.objects.get_or_create(code="SALES_MANAGER", defaults={"name": "Менеджер", "sort_order": 20})


def _seller(name, inn, *, staff_email=None):
    company = Company.objects.create(name=name, inn=inn)
    company.types.add(CompanyType.objects.get(code="SUPPLIER"))
    if staff_email:
        role = CompanyRole.objects.create(company=company, name="Каталог", permissions=["catalog.manage"])
        user = CustomUser.objects.create_user(email=staff_email, username=staff_email, password="pw")
        CompanyMember.objects.create(
            user=user,
            company=company,
            role=WorkspaceRole.objects.get(code="SALES_MANAGER"),
            company_roles=[role],
            is_active=True,
            is_primary=True,
        )
    return company


@pytest.fixture
def administrator():
    admin_role, _ = SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Администратор"})
    return CustomUser.objects.create_user(
        is_superuser=True, email="root@fix67.test", username="root@fix67.test", password="pw", role=admin_role
    )


def test_administrator_creates_a_product_for_the_own_company_without_naming_it(administrator):
    own = _seller("Своя компания", "9670000001", staff_email="staff@fix67.test")

    response = _client_for(administrator).post(URL, {"name": "Болт М24 (форма)"}, format="json")

    assert response.status_code == 201, response.content
    assert Product.objects.get(pk=response.json()["id"]).owner_company_id == own.pk


def test_an_explicitly_named_company_wins_over_the_default(administrator):
    _seller("Своя компания", "9670000001", staff_email="staff@fix67.test")
    other = _seller("Другая", "9670000002")

    response = _client_for(administrator).post(URL, {"name": "Гайка", "owner_company": other.pk}, format="json")

    assert response.status_code == 201, response.content
    assert Product.objects.get(pk=response.json()["id"]).owner_company_id == other.pk


def test_own_company_setting_resolves_the_owner_when_there_are_several_sellers(administrator, settings):
    _seller("Первая", "9670000001", staff_email="one@fix67.test")
    second = _seller("Вторая", "9670000002", staff_email="two@fix67.test")
    settings.OWN_COMPANY_ID = second.pk

    response = _client_for(administrator).post(URL, {"name": "Шайба"}, format="json")

    assert response.status_code == 201, response.content
    assert Product.objects.get(pk=response.json()["id"]).owner_company_id == second.pk


def test_ambiguous_own_company_is_a_clear_refusal_not_a_server_error(administrator, settings):
    _seller("Первая", "9670000001", staff_email="one@fix67.test")
    _seller("Вторая", "9670000002", staff_email="two@fix67.test")
    settings.OWN_COMPANY_ID = None

    response = _client_for(administrator).post(URL, {"name": "Шайба"}, format="json")

    assert response.status_code == 400
    assert response.json() == {"detail": "OWNER_COMPANY_REQUIRED"}
    assert not Product.objects.filter(name="Шайба").exists()


def test_no_own_company_yet_keeps_the_refusal(administrator):
    """Сотрудников ещё нет (свежая установка): карточка «ничья» не рождается."""
    _seller("Без сотрудников", "9670000001")

    response = _client_for(administrator).post(URL, {"name": "Ничья"}, format="json")

    assert response.status_code == 400
    assert response.json() == {"detail": "OWNER_COMPANY_REQUIRED"}


def test_staff_member_product_belongs_to_the_own_company():
    own = _seller("Своя компания", "9670000001", staff_email="staff@fix67.test")
    staff = CustomUser.objects.get(email="staff@fix67.test")

    response = _client_for(staff).post(URL, {"name": "Клапан"}, format="json")

    assert response.status_code == 201, response.content
    assert Product.objects.get(pk=response.json()["id"]).owner_company_id == own.pk

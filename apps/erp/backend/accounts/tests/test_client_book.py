"""Книга клиентов бэк-офиса (офлайн-клиенты и их контакты).

Перенесено из `crm/tests/test_relationships.py` при удалении контрагентских связей
(M1-ERP-02 волна 3): книга контрагентов с рёбрами и роллапами удалена, а заведение офлайн-клиента
и его контакты остались. Книга принадлежит своей компании — её видят её сотрудники, посторонний
(покупательский аккаунт) видит пустую книгу и не может завести клиента.
"""

import pytest
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import Company, CompanyMember, CompanyType, Contact, CustomUser, WorkspaceRole
from accounts.services.clients import create_offline_client


@pytest.fixture
def scene(db, grant):
    owner_role = WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})[0]
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Client", "sort_order": 10})[0]
    seller_type = CompanyType.objects.get_or_create(code="SUPPLIER", defaults={"name": "Supplier", "sort_order": 20})[0]

    own_company = Company.objects.create(name="Own Co", inn="R200")
    own_company.types.add(seller_type)
    buyer_company = Company.objects.create(name="Buyer Co", inn="R100")
    buyer_company.types.add(client_type)

    def member(company, email, **flags):
        user = CustomUser.objects.create_user(email=email, username=email, password="x", is_active=True)
        CompanyMember.objects.create(
            user=user, company=company, role=owner_role, is_active=True, is_primary=True, **flags
        )
        return user

    staff = member(own_company, "rs@t.test", can_sell=True)
    grant(staff, "deal.manage")  # книга клиентов — право роли «Вести запросы и сделки» (M1-ERP-05)
    return {
        "staff": staff,
        "teammate": member(own_company, "rt@t.test", can_sell=True),
        "buyer": member(buyer_company, "rb@t.test"),
    }


def _api(user):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(user).access_token}")
    return client


def _rows(response):
    body = response.json()
    return body["results"] if isinstance(body, dict) else body


def test_contact_create_and_book_scoping(scene):
    api = _api(scene["staff"])
    resp = api.post(
        "/api/v1/accounts/contacts/",
        {"company_name": "Offline LLC", "contact_name": "Пётр", "email": "p@offline.test"},
        format="json",
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["company_name"] == "Offline LLC" and body["is_primary"] is True
    assert body["company_is_registered"] is False

    assert len(_rows(api.get("/api/v1/accounts/contacts/"))) == 1
    # Книга — командная: коллега по своей компании видит того же клиента.
    assert len(_rows(_api(scene["teammate"]).get("/api/v1/accounts/contacts/"))) == 1
    # Покупательский аккаунт (не сотрудник) книгу бэк-офиса не видит.
    assert _rows(_api(scene["buyer"]).get("/api/v1/accounts/contacts/")) == []


def test_contact_create_maps_service_errors(scene):
    resp = _api(scene["staff"]).post(
        "/api/v1/accounts/contacts/",
        {"company_name": "NoReach LLC", "contact_name": "Без Контактов"},
        format="json",
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "CONTACT_NEEDS_EMAIL_OR_PHONE"


def test_offline_client_refused_for_non_staff(scene):
    result, err = create_offline_client(seller=scene["buyer"], company_name="X", contact_name="Y", email="x@y.test")
    assert result is None and err == "ONLY_SELLER_CAN_CREATE_CLIENTS"


# ── can_act: каждый путь создания контакта называет право сам (FIX-54, P-18) ─────────────────────────


def test_contact_model_default_grants_no_right_to_act(db):
    company = Company.objects.create(name="Default Co", inn="700000099")
    assert Contact.objects.create(company=company, name="Без права").can_act is False


def test_staff_created_client_contact_can_act_by_default(scene):
    """Сотрудник сам заводит клиента (звонок, офлайн) — контакт подписывает, как и было."""
    resp = _api(scene["staff"]).post(
        "/api/v1/accounts/contacts/",
        {"company_name": "Staff LLC", "contact_name": "Пётр", "email": "p@staff.test"},
        format="json",
    )
    assert resp.status_code == 201
    assert Contact.objects.get(pk=resp.json()["id"]).can_act is True


def test_staff_can_create_a_read_only_client_contact(scene):
    resp = _api(scene["staff"]).post(
        "/api/v1/accounts/contacts/",
        {"company_name": "Staff2 LLC", "contact_name": "Анна", "email": "a@staff.test", "can_act": False},
        format="json",
    )
    assert resp.status_code == 201
    assert Contact.objects.get(pk=resp.json()["id"]).can_act is False


def test_offline_client_service_states_the_right_explicitly(scene):
    result, _ = create_offline_client(
        seller=scene["staff"], company_name="Svc Co", contact_name="Иван", email="i@svc.test", can_act=False
    )
    assert result["contact"].can_act is False

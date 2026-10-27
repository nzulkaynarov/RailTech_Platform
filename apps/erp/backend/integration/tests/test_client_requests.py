"""«Создать заявку» CRM для переданного клиента: `POST /clients/{crm_client_id}/requests` (шов 0.8.0, CRM-03, W16-D1-2).

Заявка процесса v3 с номером ЗВ (ERP-09), срочностью и менеджером заявки — владельцем сделки (B-008);
`request.created(source=crm)` несёт номер, срочность, файл письма EDS и заявку CRM; идемпотентно по `crm_request_id`.
"""

from __future__ import annotations

import uuid

import pytest
from django.utils import timezone
from integration.models import CrmContactMapping, CrmUserMapping
from integration.tests import bus_support
from parties.models import CompanyType, Contact
from rest_framework.test import APIClient

from accounts.models import CustomUser
from crm.models import Deal

pytestmark = pytest.mark.django_db

SERVICE_TOKEN = "test-crm-to-erp-token"
FILE_ID = "3f2c1a7e-5b9d-4c8e-9a1f-0d2e3c4b5a69"


@pytest.fixture(autouse=True)
def integration_env(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]
    settings.CABINET_URL = "http://cabinet.localhost"
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})


@pytest.fixture
def api():
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return client


def _handoff(api, crm_client_id=1001):
    body = {
        "crm_client_id": crm_client_id,
        "crm_lead_id": 501,
        "company": {"name": "ООО Рельсы Тест", "inn": "123456789", "language": "ru"},
        "contacts": [
            {
                "crm_contact_id": crm_client_id * 10 + 1,
                "name": "Иван Иванов",
                "phone": "+998901234567",
                "language": "ru",
                "is_primary": True,
                "preferred_channel": "telegram",
                "telegram_user_id": 12345678,
            }
        ],
        "need": {"summary": "Клиент без заявки"},
        "owner": {"crm_user_id": 101, "name": "Менеджер Продаж"},
        "consent": {"given_at": "2026-10-01T09:30:00+05:00", "version": "2026-09"},
        "create_request": False,
        "invite": {"channels": ["telegram"]},
    }
    response = api.post(
        "/api/integration/v1/clients/handoff", body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
    )
    assert response.status_code == 201, response.content
    return response.json()


def _body(crm_request_id=318, **changes):
    body = {
        "crm_request_id": crm_request_id,
        "crm_lead_id": 501,
        "contact": None,
        "need": {"summary": "Нужны 20 комплектов, срок — ноябрь", "product_interest": ["Рельс Р65"]},
        "owner": {"crm_user_id": 101, "name": "Менеджер Продаж"},
        "urgency": "urgent",
        "letter_file_id": FILE_ID,
        "process": "v3",
    }
    body.update(changes)
    return body


def _create(api, body, crm_client_id=1001):
    return api.post(
        f"/api/integration/v1/clients/{crm_client_id}/requests",
        body,
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )


def _manager(crm_user_id=101):
    user = CustomUser.objects.create_user(email="manager@railtech.test", username="manager", password="pw")
    CrmUserMapping.objects.create(crm_user_id=crm_user_id, user=user)
    return user


def test_request_is_a_v3_deal_with_a_number_urgency_and_the_request_manager_as_owner(api):
    handed = _handoff(api)
    manager = _manager()

    response = _create(api, _body())

    assert response.status_code == 201, response.content
    data = response.json()
    deal = Deal.objects.get(pk=data["erp_request_id"])
    assert data == {"erp_company_id": handed["erp_company_id"], "erp_request_id": deal.pk, "number": deal.number}
    assert deal.number.startswith("ЗВ-") and deal.process == "v3" and deal.urgency == "urgent"
    assert deal.crm_request_id == 318 and deal.manager_id == manager.pk, "владелец сделки — менеджер заявки (B-008)"
    assert deal.stage.code == "DRAFT" and deal.notes == "Нужны 20 комплектов, срок — ноябрь"
    assert deal.contact.name == "Иван Иванов", "без контакта в теле — основной контакт компании"

    event = bus_support.only("request.created")
    bus_support.assert_matches_contract(event)
    payload = event["data"]["payload"]
    assert payload["source"] == "crm" and payload["erp_request_id"] == deal.pk
    assert payload["request_number"] == deal.number and event["data"]["deal"]["number"] == deal.number
    assert (payload["urgency"], payload["process"], payload["letter_file_id"], payload["crm_request_id"]) == (
        "urgent",
        "v3",
        FILE_ID,
        318,
    )
    assert payload["manager_crm_user_id"] == 101


def test_repeat_with_the_same_crm_request_returns_the_same_request_without_a_second_event(api):
    _handoff(api)
    first = _create(api, _body())
    published = len(bus_support.published("request.created"))

    again = _create(api, _body())

    assert again.status_code == 200 and again.json() == first.json()
    assert Deal.objects.filter(crm_request_id=318).count() == 1
    assert len(bus_support.published("request.created")) == published


def test_second_request_of_the_same_client_is_a_new_deal_with_the_next_number(api):
    _handoff(api)
    first = _create(api, _body(318)).json()
    second = _create(api, _body(319, urgency="normal", letter_file_id=None)).json()

    assert first["erp_request_id"] != second["erp_request_id"]
    assert int(second["number"].rsplit("-", 1)[1]) == int(first["number"].rsplit("-", 1)[1]) + 1
    payload = bus_support.published("request.created")[-1]["data"]["payload"]
    assert payload["urgency"] == "normal" and "letter_file_id" not in payload


def test_new_contact_without_email_is_created_and_mapped(api):
    """Контакт заявки, которого ERP не знает, — создаётся в компании с сопоставлением; e-mail не обязателен."""
    handed = _handoff(api)
    contact = {
        "crm_contact_id": 77001,
        "name": "Алишер Снабженцев",
        "phone": "+998907770011",
        "telegram_user_id": 55501,
        "language": "uz",
        "is_primary": False,
        "preferred_channel": "telegram",
    }

    response = _create(api, _body(contact=contact))

    assert response.status_code == 201, response.content
    deal = Deal.objects.get(pk=response.json()["erp_request_id"])
    created = Contact.objects.get(company_id=handed["erp_company_id"], name="Алишер Снабженцев")
    assert deal.contact_id == created.pk and created.email == "" and created.telegram_user_id == 55501
    assert CrmContactMapping.objects.get(crm_contact_id=77001).contact_id == created.pk


def test_known_contact_is_reused(api):
    _handoff(api)
    known = CrmContactMapping.objects.get(crm_contact_id=10011).contact
    contact = {
        "crm_contact_id": 10011,
        "name": "Иван Иванов",
        "language": "ru",
        "is_primary": True,
        "preferred_channel": "telegram",
    }

    deal = Deal.objects.get(pk=_create(api, _body(contact=contact)).json()["erp_request_id"])

    assert deal.contact_id == known.pk
    assert Contact.objects.filter(company=known.company).count() == 1


def test_client_not_handed_off_is_404_and_nothing_is_created(api):
    response = _create(api, _body(), crm_client_id=4242)

    assert response.status_code == 404 and response.json() == {"detail": "CLIENT_NOT_FOUND"}
    assert not Deal.objects.filter(crm_request_id=318).exists()


@pytest.mark.parametrize(
    "broken",
    [
        {"urgency": "asap"},
        {"process": "legacy"},
        {"need": {"summary": ""}},
        {"crm_request_id": 0},
        {"letter_file_id": "not-a-uuid"},
    ],
)
def test_invalid_body_is_422(api, broken):
    _handoff(api)
    response = _create(api, _body(**broken))
    assert response.status_code == 422 and response.json() == {"detail": "VALIDATION_ERROR"}


def test_without_a_mapped_manager_the_deal_has_no_owner(api):
    _handoff(api)
    deal = Deal.objects.get(
        pk=_create(api, _body(owner={"crm_user_id": 999, "name": "Новый"})).json()["erp_request_id"]
    )
    assert deal.manager_id is None


def test_handoff_request_also_gets_the_request_manager_as_owner(api):
    """B-008 и для заявки из передачи (`create_request: true`): владелец сделки — менеджер CRM."""
    manager = _manager()
    body = {
        "crm_client_id": 2002,
        "company": {"name": "ООО Вторая", "inn": "987654321", "language": "ru"},
        "contacts": [
            {
                "crm_contact_id": 20021,
                "name": "Пётр",
                "language": "ru",
                "is_primary": True,
                "preferred_channel": "email",
            }
        ],
        "need": {"summary": "Поставка"},
        "owner": {"crm_user_id": 101, "name": "Менеджер Продаж"},
        "consent": {"given_at": timezone.now().isoformat(), "version": "2026-09"},
        "create_request": True,
        "invite": {"channels": ["email"]},
    }
    response = api.post(
        "/api/integration/v1/clients/handoff", body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4())
    )
    assert response.status_code == 201, response.content
    assert Deal.objects.get(pk=response.json()["erp_request_id"]).manager_id == manager.pk


def test_same_idempotency_key_with_a_changed_body_is_409_and_nothing_is_overwritten(api):
    """Ключ идемпотентности шва (детерминированный от заявки CRM) с изменённым телом — 409 `IDEMPOTENCY_CONFLICT`:
    вторая сделка не создаётся, первая не перезаписывается."""
    _handoff(api)
    key = str(uuid.uuid4())
    url = "/api/integration/v1/clients/1001/requests"
    first = api.post(url, _body(), format="json", HTTP_IDEMPOTENCY_KEY=key)
    assert first.status_code == 201

    changed = api.post(url, _body(urgency="normal"), format="json", HTTP_IDEMPOTENCY_KEY=key)

    assert changed.status_code == 409 and changed.json() == {"detail": "IDEMPOTENCY_CONFLICT"}
    deal = Deal.objects.get(crm_request_id=318)
    assert deal.urgency == "urgent", "первая заявка не перезаписана"
    assert Deal.objects.filter(crm_request_id__isnull=False).count() == 1

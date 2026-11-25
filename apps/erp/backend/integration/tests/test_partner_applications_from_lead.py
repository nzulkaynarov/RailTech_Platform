"""«Партнёр» из карточки лида CRM: `POST /partner-applications` (ЛП-1).

Заявка кандидата `source = lead`, `source_ref` — номер лида; идемпотентно по номеру лида — повтор и параллельный повтор
не задваивают очередь «Заявки партнёров»; отклонённая заявка не блокирует новую подачу того же лида.
"""

from __future__ import annotations

import threading
import uuid

import pytest
from django.db import connection
from parties.models import PartnerApplication, PartnerApplicationSource, PartnerApplicationStatus
from rest_framework.test import APIClient

SERVICE_TOKEN = "test-crm-to-erp-token"
URL = "/api/integration/v1/partner-applications"


@pytest.fixture(autouse=True)
def integration_env(settings):
    settings.SERVICE_TOKEN_CRM_TO_ERP = [SERVICE_TOKEN]


def _api() -> APIClient:
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {SERVICE_TOKEN}")
    return client


def _body(lead=77, **over):
    body = {
        "crm_lead_id": lead,
        "lead_number": f"L-{lead:04d}",
        "company_name": "Контур Партнёр",
        "country": "UZ",
        "inn": "301234567",
        "kind": "supplier",
        "categories_description": "Поставка крепежа",
        "contact_name": "Иван Партнёров",
        "email": "Partner@Example.test",
        "phone": "+998901234567",
        "language": "ru",
    }
    body.update(over)
    return body


def _post(api, body):
    return api.post(URL, body, format="json", HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()))


@pytest.mark.django_db
def test_creates_application_from_lead():
    response = _post(_api(), _body())
    assert response.status_code == 201, response.content
    assert response.json()["created"] is True
    app = PartnerApplication.objects.get()
    assert (app.source, app.source_ref) == (PartnerApplicationSource.LEAD, "L-0077")
    assert (app.company_name, app.inn, app.email, app.consent) == (
        "Контур Партнёр",
        "301234567",
        "partner@example.test",
        False,
    )
    assert app.status == PartnerApplicationStatus.SUBMITTED


@pytest.mark.django_db
def test_repeat_returns_the_same_application_with_a_new_key():
    api = _api()
    first = _post(api, _body()).json()
    second = _post(api, _body())
    assert second.status_code == 200
    assert second.json() == {**first, "created": False}
    assert PartnerApplication.objects.count() == 1


@pytest.mark.django_db
def test_rejected_application_does_not_block_a_new_one():
    api = _api()
    _post(api, _body())
    PartnerApplication.objects.update(status=PartnerApplicationStatus.REJECTED)
    assert _post(api, _body()).status_code == 201
    assert PartnerApplication.objects.count() == 2


@pytest.mark.django_db
def test_email_is_optional_but_must_be_valid_when_given():
    api = _api()
    assert _post(api, _body(lead=78, email="")).status_code == 201
    assert _post(api, _body(lead=79, email="not-an-email")).status_code == 422


@pytest.mark.django_db(transaction=True)
def test_concurrent_submits_create_one_application():
    """Два одновременных запроса с разными ключами: блокировка на номер лида — одна строка; без неё — две."""
    results = []
    barrier = threading.Barrier(2)

    def submit():
        try:
            barrier.wait(timeout=10)
            results.append(_post(_api(), _body(lead=90)).status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=submit) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert sorted(results) == [200, 201]
    assert PartnerApplication.objects.filter(source_ref="L-0090").count() == 1

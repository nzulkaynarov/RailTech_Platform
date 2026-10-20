"""FIX-55 / m2 D-2: `POST /crm/fulfillments/update-status/` не падает 500.

Отгрузку создаёт Celery-задача после подписания договора. Пока её нет (или сделка не существует), сервис
делал `.get(deal_id=…)` без обработки и отвечал 500, а нечисловой `deal_id` ронял `int()` во вью.
Теперь: нет отгрузки — 409 `FULFILLMENT_NOT_READY`; нет сделки — 404 `NOT_FOUND`; мусорный `deal_id` — 400 `DEAL_ID_INVALID`.
"""

import pytest
from rest_framework.test import APIClient

from crm import services as crm_services
from crm.tests.test_fulfillment_service import lookups, world  # noqa: F401

URL = "/api/v1/crm/fulfillments/update-status/"


def _client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_service_reports_fulfillment_not_ready(world):  # noqa: F811
    obj, err = crm_services.update_fulfillment_status(world["deal"].id, world["superuser"], "SHIPPED")
    assert obj is None and err == "FULFILLMENT_NOT_READY"


@pytest.mark.django_db
def test_service_reports_unknown_deal(world):  # noqa: F811
    obj, err = crm_services.update_fulfillment_status(10**9, world["superuser"], "SHIPPED")
    assert obj is None and err == "NOT_FOUND"


@pytest.mark.django_db
def test_endpoint_before_fulfillment_exists_is_409(world):  # noqa: F811
    response = _client(world["superuser"]).post(URL, {"deal_id": world["deal"].id, "status": "SHIPPED"}, format="json")
    assert response.status_code == 409, response.content
    assert response.json()["detail"] == "FULFILLMENT_NOT_READY"


@pytest.mark.django_db
def test_endpoint_unknown_deal_is_404(world):  # noqa: F811
    response = _client(world["superuser"]).post(URL, {"deal_id": 10**9, "status": "SHIPPED"}, format="json")
    assert response.status_code == 404, response.content
    assert response.json()["detail"] == "NOT_FOUND"


@pytest.mark.django_db
@pytest.mark.parametrize("garbage", ["abc", "1; DROP TABLE", "12.5x", [1], {"a": 1}])
def test_endpoint_non_numeric_deal_id_is_400(world, garbage):  # noqa: F811
    response = _client(world["superuser"]).post(URL, {"deal_id": garbage, "status": "SHIPPED"}, format="json")
    assert response.status_code == 400, response.content
    assert response.json()["detail"] == "DEAL_ID_INVALID"


@pytest.mark.django_db
def test_endpoint_works_once_fulfillment_exists(world):  # noqa: F811
    crm_services.ensure_fulfillment(world["deal"])
    response = _client(world["superuser"]).post(URL, {"deal_id": world["deal"].id, "status": "SHIPPED"}, format="json")
    assert response.status_code == 200, response.content


@pytest.mark.django_db
def test_unauthorized_actor_learns_nothing_about_the_deal(world):  # noqa: F811
    """Право проверяется раньше 404/409: посторонний не отличает «сделки нет» от «отгрузки ещё нет»."""
    outsider = world["other_seller"]  # участник чужой компании-клиента, не продавец

    no_fulfillment = crm_services.update_fulfillment_status(world["deal"].id, outsider, "SHIPPED")
    no_deal = crm_services.update_fulfillment_status(10**9, outsider, "SHIPPED")

    assert no_fulfillment == no_deal == (None, "MEMBER_REQUIRED_FOR_ACTION")

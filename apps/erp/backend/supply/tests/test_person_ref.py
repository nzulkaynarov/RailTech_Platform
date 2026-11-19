"""СУЩ-3: «кто сделал» на складе и в заказах — ссылка `{crm_user_id, name}` рядом с прежним именем.

По `crm_user_id` Платформа берёт фото и должность из справочника CRM; пользователь без связи с CRM — `crm_user_id: None`.
"""

from __future__ import annotations

import pytest
from integration.models import CrmUserMapping
from inventory.tests.support import api

pytestmark = pytest.mark.django_db

STOCK = "/api/v1/stock/"


def _adjust(world, quantity=5):
    body = {"product_id": world["rail"].pk, "quantity": quantity, "cell": "A-01"}
    response = api(world["supply"]).post(f"{STOCK}adjustments/", body, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def test_movement_names_the_employee_with_his_crm_id(world):
    CrmUserMapping.objects.create(user=world["supply"], crm_user_id=77)

    [movement] = _adjust(world)["movements"]

    assert movement["by"] == {"crm_user_id": 77, "name": movement["by_name"]}


def test_user_without_crm_link_keeps_the_name_and_no_id(world):
    [movement] = _adjust(world)["movements"]
    assert movement["by"]["crm_user_id"] is None
    assert movement["by"]["name"] == movement["by_name"]


def test_supplier_order_author_and_log_carry_the_ref(world):
    CrmUserMapping.objects.create(user=world["supply"], crm_user_id=78)
    body = {"supplier_id": world["vendor"].pk, "lines": [{"product_id": world["rail"].pk, "quantity": 3}]}
    created = api(world["supply"]).post(f"{STOCK}orders/", body, format="json")
    assert created.status_code == 201, created.json()
    order = api(world["supply"]).get(f"{STOCK}orders/{created.json()['id']}/").json()

    assert order["created_by"]["crm_user_id"] == 78
    assert {entry["by"]["crm_user_id"] for entry in order["log"] if entry["by"]} == {78}

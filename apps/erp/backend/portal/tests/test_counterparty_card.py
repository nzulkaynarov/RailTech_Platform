"""СУЩ-2.5 (ADR-0028): карточка контрагента — одна компания во всех ролях.

`GET /api/v1/parties/organizations/{id}/`, `GET /api/v1/parties/crm-clients/{id}/organization/`,
`POST /api/v1/parties/organizations/{id}/roles/`. Мир —
`catalog.tests.desk_world`: поставщик с предложениями; клиент — из книги своей компании.
"""

import pytest
from integration.models import CrmClientMapping
from parties.models import Company, Contact

from accounts.services.bank_accounts import set_uzs_account
from catalog.models import Manufacturer
from catalog.tests.desk_world import build_world
from core.models import Country, Currency

pytestmark = pytest.mark.django_db

URL = "/api/v1/parties/organizations/"
BY_CLIENT = "/api/v1/parties/crm-clients/{}/organization/"


@pytest.fixture
def world():
    world = build_world()
    Country.objects.get_or_create(code="UZ", defaults={"name": "Узбекистан"})
    Currency.objects.update_or_create(code="UZS", defaults={"name": "Сум", "iso_numeric": "860"})
    staff = world["users"]["supply"]
    supplier = world["supplier"]
    # та же компания — ещё и клиент: контакт заведён сотрудником, связана с клиентом CRM
    Contact.objects.create(
        company=supplier, name="Рустам Ахмедов", position="Снабжение", is_primary=True, created_by=staff, phone="+998"
    )
    Contact.objects.create(company=supplier, name="Нилуфар Каримова", position="Бухгалтер", can_act=True)
    assert set_uzs_account(supplier, "20208000900001234567", "00440", bank_name="АКБ Образец") == {}
    CrmClientMapping.objects.create(crm_client_id=42, company=supplier)
    Manufacturer.objects.create(name="PL-Rail", company=supplier)
    stranger = Company.objects.create(name="ООО Чужой", inn="300000999")
    Contact.objects.create(company=stranger, name="Чужой Контакт")
    world["stranger"] = stranger
    return world


def card(world, who="supply"):
    return world["clients"][who].get(f"{URL}{world['supplier'].pk}/")


def test_one_company_in_all_roles(world):
    response = card(world)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body["name"] == "ООО Поставщик Север" and body["crm_client_id"] == 42
    assert body["roles"] == {"client": True, "supplier": True, "manufacturer": False, "partner": False}
    assert [(p["name"], p["is_primary"], p["has_cabinet"]) for p in body["people"]] == [
        ("Рустам Ахмедов", True, False),
        ("Нилуфар Каримова", False, True),
    ]
    assert "phone" not in body["people"][0] and body["people"][0]["has_phone"] is True
    assert body["brands"] == [{"id": body["brands"][0]["id"], "name": "PL-Rail"}]
    assert world["clients"]["supply"].get(BY_CLIENT.format(42)).json()["id"] == body["id"]
    assert world["clients"]["supply"].get(BY_CLIENT.format(777)).status_code == 404


def test_account_number_is_full_only_for_finance(world):
    masked = card(world, "manager").json()
    assert masked["accounts_masked"] is True
    assert masked["bank_accounts"][0]["account"] == "…4567"
    full = card(world, "accountant").json()
    assert full["accounts_masked"] is False
    assert full["bank_accounts"][0] == {
        "id": full["bank_accounts"][0]["id"],
        "currency": "UZS",
        "bank_name": "АКБ Образец",
        "bank_country": "UZ",
        "account": "2020 8000 9000 0123 4567",
        "mfo": "00440",
        "swift": "",
        "is_default": True,
    }


def test_roles_are_marks_not_new_cards(world):
    client = world["clients"]["supply"]
    url = f"{URL}{world['supplier'].pk}/roles/"
    companies = Company.objects.count()

    marked = client.post(url, {"role": "manufacturer", "on": True}, format="json")
    assert marked.status_code == 200, marked.content
    assert marked.json()["roles"]["manufacturer"] is True
    assert Company.objects.count() == companies

    # роль занята данными: есть бренд и предложения
    assert client.post(url, {"role": "manufacturer", "on": False}, format="json").json() == {"detail": "ROLE_IN_USE"}
    assert client.post(url, {"role": "supplier", "on": False}, format="json").status_code == 409
    Manufacturer.objects.filter(company=world["supplier"]).update(company=None)
    assert (
        client.post(url, {"role": "manufacturer", "on": False}, format="json").json()["roles"]["manufacturer"] is False
    )

    assert client.post(url, {"role": "client", "on": True}, format="json").status_code == 400
    assert world["clients"]["manager"].post(url, {"role": "manufacturer", "on": True}, format="json").status_code == 403


def test_strangers_and_own_company_have_no_card(world):
    client = world["clients"]["supply"]
    assert client.get(f"{URL}{world['stranger'].pk}/").status_code == 404
    assert client.get(f"{URL}{world['own'].pk}/").status_code == 404

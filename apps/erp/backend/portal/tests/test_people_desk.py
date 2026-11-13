"""FR-11 (пункт 0.11): `/api/v1/parties/people/` — люди клиентов и партнёров для «Органайзер · Люди» Платформы.

Клиенты — книга своей компании (контакт заведён сотрудником), партнёры — поставщики и компании с отношением «партнёр»;
своя компания и чужие клиенты не входят. Мир — `catalog.tests.desk_world`.
"""

import pytest
from parties.models import Company, CompanyRelationship, Contact

from catalog.tests.desk_world import build_world

pytestmark = pytest.mark.django_db

URL = "/api/v1/parties/people/"


@pytest.fixture
def world():
    world = build_world()
    staff = world["users"]["supply"]
    client = Company.objects.create(name="ООО Клиент Юг", inn="300000555")
    Contact.objects.create(company=client, name="Анвар Клиентов", position="Главный инженер", created_by=staff)
    Contact.objects.create(company=world["supplier"], name="Дильшод Поставщиков", email="d@north.example.uz")
    partner = Company.objects.create(name="ООО Изготовитель", inn="300000666")
    CompanyRelationship.objects.create(company=partner, role="partner")
    Contact.objects.create(company=partner, name="Бахром Партнёров")
    Contact.objects.create(company=world["own"], name="Свой Сотрудников")
    stranger = Company.objects.create(name="ООО Чужой", inn="300000999")
    Contact.objects.create(company=stranger, name="Чужой Контакт")
    world["client_company"] = client
    return world


def names(body):
    return [row["name"] for row in body["results"]]


def test_clients_and_partners_without_own_and_strangers(world):
    response = world["clients"]["supply"].get(URL)
    assert response.status_code == 200, response.content
    body = response.json()
    assert names(body) == ["Анвар Клиентов", "Бахром Партнёров", "Дильшод Поставщиков"]
    anvar = body["results"][0]
    assert anvar == {
        "id": anvar["id"],
        "name": "Анвар Клиентов",
        "position": "Главный инженер",
        "has_email": False,
        "has_phone": False,
        "is_primary": False,
        "company": {"id": world["client_company"].pk, "name": "ООО Клиент Юг"},
        "kind": "client",
    }
    assert {row["name"]: row["kind"] for row in body["results"]}["Дильшод Поставщиков"] == "partner"


def test_filter_by_kind_and_search(world):
    client = world["clients"]["supply"]
    assert names(client.get(URL, {"kind": "client"}).json()) == ["Анвар Клиентов"]
    assert names(client.get(URL, {"kind": "partner"}).json()) == ["Бахром Партнёров", "Дильшод Поставщиков"]
    assert names(client.get(URL, {"q": "изготовитель"}).json()) == ["Бахром Партнёров"]
    assert names(client.get(URL, {"q": "инженер"}).json()) == ["Анвар Клиентов"]
    # неизвестный вид — как без фильтра
    assert len(client.get(URL, {"kind": "own"}).json()["results"]) == 3


def test_every_staff_role_reads(world):
    for who, client in world["clients"].items():
        assert client.get(URL).status_code == 200, who


def test_anonymous_is_401():
    from rest_framework.test import APIClient

    assert APIClient().get(URL).status_code == 401


def test_contacts_of_one_person_within_the_same_bounds(world):
    client = world["clients"]["supply"]
    people = client.get(URL).json()["results"]
    dilshod = next(row for row in people if row["name"] == "Дильшод Поставщиков")
    assert (dilshod["has_email"], dilshod["has_phone"]) == (True, False)
    assert "email" not in dilshod  # массовой выгрузки контактов нет
    one = client.get(f"{URL}{dilshod['id']}/")
    assert one.status_code == 200
    assert one.json() == {
        "id": dilshod["id"],
        "name": "Дильшод Поставщиков",
        "phone": None,
        "email": "d@north.example.uz",
    }
    stranger = Contact.objects.get(name="Чужой Контакт")
    assert client.get(f"{URL}{stranger.pk}/").status_code == 404

"""СЦ-12: книга клиентов своей компании — по фактам (тип CLIENT, связь с клиентом CRM, сделка), а не по автору контакта.

Прогон сценариев: клиент из CRM не находился адресатом письма, а поставщик, чей контакт завёл сотрудник, числился
клиентом. Мир — `catalog.tests.desk_world` (своя компания, сотрудники, поставщик) и `integration.tests.world`.
"""

import pytest
from integration.models import CrmClientMapping
from integration.tests.world import make_company, make_deal
from parties.models import Company, CompanyType, Contact

from accounts.models import CustomUser
from accounts.services.clients import seller_clients
from catalog.tests.desk_world import build_world

pytestmark = pytest.mark.django_db

ORGS = "/api/v1/parties/organizations/"
PEOPLE = "/api/v1/parties/people/"
BY_CRM_CLIENT = "/api/v1/parties/crm-clients/{}/organization/"


def client_type():
    return CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})[0]


@pytest.fixture
def world():
    world = build_world()
    world["staff"] = world["users"]["supply"]
    world["api"] = world["clients"]["supply"]
    return world


def orgs(world, q):
    response = world["api"].get(ORGS, {"q": q})
    assert response.status_code == 200
    return [(row["name"], row["kind"]) for row in response.json()["results"]]


@pytest.mark.parametrize("fact", ["type", "crm", "deal"])
def test_each_fact_alone_makes_a_client(world, fact):
    company = Company.objects.create(name="ООО Факт", inn="300000801")
    Contact.objects.create(company=company, name="Фарход Фактов")  # без автора: так приходят контакты из CRM
    if fact == "type":
        company.types.add(client_type())
    elif fact == "crm":
        CrmClientMapping.objects.create(crm_client_id=801, company=company)
    else:
        make_deal(company)

    assert company in seller_clients(world["staff"])
    assert orgs(world, "Факт") == [("ООО Факт", "client")]


def test_crm_client_is_an_addressee_a_client_person_and_has_a_card(world):
    company = make_company("ООО Метро Клиент", crm_client_id=7001, inn="300000802")

    assert orgs(world, "Метро") == [("ООО Метро Клиент", "client")]
    assert orgs(world, "300000802") == [("ООО Метро Клиент", "client")]
    people = world["api"].get(PEOPLE, {"kind": "client"}).json()["results"]
    assert "Иван" in [row["name"] for row in people]
    card = world["api"].get(BY_CRM_CLIENT.format(7001))
    assert card.status_code == 200
    assert card.json()["roles"]["client"] is True
    assert company in seller_clients(world["staff"])


def test_crm_client_linked_by_inn_without_client_type(world):
    """Передача из CRM в найденную по ИНН компанию: тип CLIENT не ставится, сопоставление непроверенное."""
    company = Company.objects.create(name="ООО Найденная", inn="300000803")
    CrmClientMapping.objects.create(crm_client_id=803, company=company, verified_at=None)
    Contact.objects.create(company=company, name="Нодир Найденов")

    assert company in seller_clients(world["staff"])
    assert orgs(world, "Найденная") == [("ООО Найденная", "client")]


def test_supplier_with_staff_contact_is_a_partner(world):
    supplier = world["supplier"]
    Contact.objects.create(company=supplier, name="Рустам Снабженцев", created_by=world["staff"])

    assert supplier not in seller_clients(world["staff"])
    people = world["api"].get(PEOPLE).json()["results"]
    assert [row["kind"] for row in people if row["name"] == "Рустам Снабженцев"] == ["partner"]
    assert orgs(world, "Поставщик Север") == [("ООО Поставщик Север", "partner")]
    card = world["api"].get(f"{ORGS}{supplier.pk}/")
    assert card.status_code == 200
    assert card.json()["roles"]["client"] is False


def test_contact_author_alone_does_not_make_a_client(world):
    company = Company.objects.create(name="ООО Только Контакт", inn="300000805")
    Contact.objects.create(company=company, name="Олим Контактов", created_by=world["staff"])

    assert company not in seller_clients(world["staff"])
    assert orgs(world, "Только Контакт") == []
    assert world["api"].get(f"{ORGS}{company.pk}/").status_code == 404


def test_own_company_is_never_a_client(world):
    own = world["own"]
    own.types.add(client_type())
    make_deal(own)

    assert own not in seller_clients(world["staff"])
    assert orgs(world, own.name) == []


def test_non_staff_book_is_empty(world):
    make_company("ООО Чей-то Клиент", crm_client_id=7007, inn="300000807")
    outsider = CustomUser.objects.create_user(email="out@x.uz", username="out@x.uz", password="pw")

    assert seller_clients(outsider).count() == 0


def test_organizations_search_by_stated_inn(world):
    """Клиент, записанный сотрудником, хранит ИНН в `stated_inn` — адресат находится и по нему."""
    company = Company.objects.create(name="ООО Офлайн", stated_inn="305123456")
    company.types.add(client_type())

    assert orgs(world, "305123456") == [("ООО Офлайн", "client")]

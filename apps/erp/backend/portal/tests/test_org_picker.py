"""ЕД-6 (PR-1): `/api/v1/parties/organizations/` как источник поля выбора контрагента.

Строка списка несёт роли, страну и клиента CRM; `q` ставит точный ИНН первым, `role` поднимает компании с ролью, но
никого не скрывает; `limit` — до 20 строк. Люди организации — с почтой и должностью. Заведение — с ролью и 409 с `id`
уже существующей компании (поиск среди ВСЕХ компаний). Мир — `catalog.tests.desk_world`.
"""

import pytest
from integration.models import CrmClientMapping
from parties.models import Company, CompanyRelationship, CompanyType, Contact

from catalog.models import Manufacturer
from catalog.tests.desk_world import build_world
from core.models import Country

pytestmark = pytest.mark.django_db

ORGS = "/api/v1/parties/organizations/"


@pytest.fixture
def world():
    world = build_world()
    uz = Country.objects.get_or_create(code="UZ", defaults={"name": "Узбекистан"})[0]
    client = Company.objects.create(name="ООО Клиент Юг", inn="500000555", country=uz)
    client.types.add(CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})[0])
    CrmClientMapping.objects.create(crm_client_id=42, company=client)
    Contact.objects.create(company=client, name="Анвар Клиентов", position="Главный инженер", email="a@yug.example.uz")
    Contact.objects.create(company=client, name="Бекзод Второй", is_primary=True, phone="+998901112233")
    maker = Company.objects.create(name="ООО Изготовитель", inn="500000666")
    maker.types.add(CompanyType.objects.get_or_create(code="MANUFACTURER", defaults={"name": "Изготовитель"})[0])
    Manufacturer.objects.create(name="PL", company=maker)
    partner = Company.objects.create(name="ООО Партнёр Восток", inn="500000777")
    CompanyRelationship.objects.create(company=partner, role="partner")
    bank = Company.objects.create(name="Банк Образец", inn="500000888")
    bank.types.add(CompanyType.objects.get_or_create(code="ORGANIZATION", defaults={"name": "Организация"})[0])
    # чужая компания: не клиент, не поставщик, без роли — в список выбора не входит, но ИНН занят
    stranger = Company.objects.create(name="ООО Чужой", inn="500000999")
    world.update(client_company=client, maker=maker, partner=partner, bank=bank, stranger=stranger)
    return world


def rows(response):
    assert response.status_code == 200, response.content
    return response.json()["results"]


def test_row_carries_roles_country_and_crm_client(world):
    by_name = {r["name"]: r for r in rows(world["clients"]["supply"].get(ORGS))}
    assert by_name["ООО Клиент Юг"]["roles"] == {
        "client": True,
        "supplier": False,
        "manufacturer": False,
        "partner": False,
        "organization": False,
    }
    assert (by_name["ООО Клиент Юг"]["country"], by_name["ООО Клиент Юг"]["crm_client_id"]) == ("Узбекистан", 42)
    assert by_name["ООО Изготовитель"]["roles"]["manufacturer"] is True
    assert by_name["ООО Изготовитель"]["country"] is None and by_name["ООО Изготовитель"]["crm_client_id"] is None
    assert by_name["ООО Партнёр Восток"]["roles"]["partner"] is True
    assert by_name["Банк Образец"]["roles"]["organization"] is True
    assert by_name[world["supplier"].name]["roles"]["supplier"] is True
    assert "ООО Чужой" not in by_name


def test_exact_inn_comes_first_not_alphabetical(world):
    # «300000555» входит в ИНН как часть у других компаний нет, поэтому заводим компанию, чей ИНН содержит искомый
    longer = Company.objects.create(name="Аа Компания", inn="5000005550")
    longer.types.add(CompanyType.objects.get_or_create(code="ORGANIZATION", defaults={"name": "Организация"})[0])
    found = [r["name"] for r in rows(world["clients"]["supply"].get(ORGS, {"q": "500000555"}))]
    assert found == ["ООО Клиент Юг", "Аа Компания"]


def test_role_raises_matching_rows_but_hides_nobody(world):
    client = world["clients"]["supply"]
    plain = [r["name"] for r in rows(client.get(ORGS))]
    raised = [r["name"] for r in rows(client.get(ORGS, {"role": "manufacturer"}))]
    assert raised[0] == "ООО Изготовитель"
    assert sorted(raised) == sorted(plain)  # те же строки, другой порядок
    assert raised[1:] == [name for name in plain if name != "ООО Изготовитель"]
    by_client = [r["name"] for r in rows(client.get(ORGS, {"role": "client"}))]
    assert by_client[0] == "ООО Клиент Юг"
    assert [r["name"] for r in rows(client.get(ORGS, {"role": "нет-такой"}))] == plain


def test_limit_is_capped_at_twenty(world):
    for i in range(25):
        extra = Company.objects.create(name=f"Орг {i:02d}", inn=f"4000000{i:02d}")
        extra.types.add(CompanyType.objects.get_or_create(code="ORGANIZATION", defaults={"name": "Организация"})[0])
    client = world["clients"]["supply"]
    assert len(rows(client.get(ORGS, {"limit": 500}))) == 20
    assert len(rows(client.get(ORGS, {"limit": 3}))) == 3
    assert client.get(ORGS).json()["count"] > 20  # без limit — обычная постраничная выдача


def test_people_of_an_organization_with_email_and_position(world):
    client = world["clients"]["supply"]
    response = client.get(f"{ORGS}{world['client_company'].pk}/people/")
    assert response.status_code == 200, response.content
    people = response.json()["results"]
    assert [(p["name"], p["position"], p["email"], p["is_primary"]) for p in people] == [
        ("Бекзод Второй", None, None, True),
        ("Анвар Клиентов", "Главный инженер", "a@yug.example.uz", False),
    ]
    assert "phone" not in people[0]
    assert client.get(f"{ORGS}{world['stranger'].pk}/people/").status_code == 404


def test_create_conflict_names_the_existing_company_even_if_hidden(world):
    manager = world["clients"]["manager"]
    taken = manager.post(ORGS, {"name": "Другое имя", "tin": world["stranger"].inn}, format="json")
    assert (taken.status_code, taken.json()) == (
        409,
        {"detail": "COMPANY_EXISTS", "existing_id": world["stranger"].pk},
    )
    same_name = manager.post(ORGS, {"name": "банк образец"}, format="json")
    assert (same_name.status_code, same_name.json()["existing_id"]) == (409, world["bank"].pk)


def test_create_with_role(world):
    supply = world["clients"]["supply"]
    made = supply.post(ORGS, {"name": "ООО Новый Поставщик", "tin": "301000111", "role": "supplier"}, format="json")
    assert made.status_code == 201, made.content
    assert made.json()["roles"]["supplier"] is True and made.json()["roles"]["organization"] is False
    plain = supply.post(ORGS, {"name": "ООО Новый Адресат", "tin": "301000222"}, format="json")
    assert plain.json()["roles"]["organization"] is True and plain.json()["roles"]["supplier"] is False
    # новый поставщик сразу виден в списке выбора
    assert "ООО Новый Поставщик" in [r["name"] for r in rows(supply.get(ORGS, {"q": "301000111"}))]


def test_supplier_role_needs_supply_permission(world):
    manager = world["clients"]["manager"]  # права действий нет
    denied = manager.post(ORGS, {"name": "ООО Без Права", "tin": "301000333", "role": "supplier"}, format="json")
    assert (denied.status_code, denied.json()["detail"]) == (403, "ROLE_PERMISSION_REQUIRED")
    assert not Company.objects.filter(inn="301000333").exists()
    assert manager.post(ORGS, {"name": "ООО Адресат", "tin": "301000444"}, format="json").status_code == 201

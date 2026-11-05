"""PART-3: «Цены товаров в каталоге» в блоке «Доступ в кабинет» карточки поставщика — настройка отношения партнёра.

Пусто — как у компании, `cabinet` — показывать, `on_request` — по запросу. Менять может тот же, кто ведёт поставщиков
(`supply.manage`); правка действует на каталог сразу и остаётся в истории отношения (pghistory) и журнале.
"""

import pytest
from parties.models import CompanyRelationship, CompanyRelationshipEvent, Contact

from catalog.tests.desk_world import build_world
from crm.models import ActivityLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def world(settings):
    world = build_world()
    settings.OWN_COMPANY_ID = world["own"].pk
    Contact.objects.create(company=world["supplier"], name="Контакт", email="c@s.example.uz")
    world["relation"] = CompanyRelationship.objects.create(
        company=world["supplier"], role="partner", status="active", modules=["my_products"]
    )
    return world


def patch(world, who, body):
    return world["clients"][who].patch(
        f"/api/v1/catalog/supplier-access/{world['supplier'].pk}/relationship/", body, format="json"
    )


def test_state_carries_the_current_value(world):
    state = world["clients"]["supply"].get(f"/api/v1/catalog/supplier-access/{world['supplier'].pk}/").json()
    assert state["relationship"]["catalog_price_visibility"] == ""


@pytest.mark.parametrize("value", ["cabinet", "on_request", ""])
def test_setting_is_saved_and_returned(world, value):
    response = patch(world, "supply", {"catalog_price_visibility": value})
    assert response.status_code == 200, response.content
    assert response.json()["relationship"]["catalog_price_visibility"] == value
    world["relation"].refresh_from_db()
    assert world["relation"].catalog_price_visibility == value


def test_other_values_are_refused_and_nothing_changes(world):
    patch(world, "supply", {"catalog_price_visibility": "cabinet"})
    response = patch(world, "supply", {"catalog_price_visibility": "everybody"})
    assert response.status_code == 400
    world["relation"].refresh_from_db()
    assert world["relation"].catalog_price_visibility == "cabinet"


@pytest.mark.parametrize("who", ["manager", "accountant", "viewer"])
def test_without_supply_manage_it_is_403(world, who):
    assert patch(world, who, {"catalog_price_visibility": "cabinet"}).status_code == 403
    world["relation"].refresh_from_db()
    assert world["relation"].catalog_price_visibility == ""


def test_without_a_relationship_it_is_404(world):
    world["relation"].delete()
    assert patch(world, "supply", {"catalog_price_visibility": "cabinet"}).status_code == 404


def test_change_is_in_the_history_and_the_journal(world):
    patch(world, "supply", {"catalog_price_visibility": "cabinet"})
    events = CompanyRelationshipEvent.objects.filter(pgh_obj=world["relation"]).order_by("pgh_id")
    assert events.last().catalog_price_visibility == "cabinet"
    entry = ActivityLog.objects.get(event_code="admin.supplier_access.rights_changed")
    assert (
        entry.after_data["catalog_price_visibility"] == "cabinet"
        and entry.before_data["catalog_price_visibility"] == ""
    )


def test_setting_changes_what_the_client_sees_at_once(world):
    from catalog.constants import MODE_CLIENT
    from catalog.published import project

    cable = world["cable"]
    cable.source_supplier = world["supplier"]
    cable.list_price = 12500
    cable.list_price_currency = world["uzs"]
    cable.save()
    assert project(cable, mode=MODE_CLIENT)["price"] is None
    patch(world, "supply", {"catalog_price_visibility": "cabinet"})
    assert project(cable, mode=MODE_CLIENT)["price"] == {"amount": "12500.00", "currency": "UZS"}
    patch(world, "supply", {"catalog_price_visibility": ""})
    assert project(cable, mode=MODE_CLIENT)["price"] is None

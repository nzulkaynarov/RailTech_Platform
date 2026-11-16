"""ADR-0027: каталог Платформы · «Новые из заявок» — черновики из строк расчёта и КП, спрос, заявки, подсказка дубля, слияние."""

from decimal import Decimal

import pytest

from catalog.models import Product, ProductStatus
from catalog.tests.desk_world import build_world
from crm.models import Deal, DealStage, Quote, QuoteItem, QuoteStatus

pytestmark = pytest.mark.django_db

URL = "/api/v1/catalog/items/"


@pytest.fixture
def world():
    data = build_world()
    stage = DealStage.objects.get_or_create(code="RFQ_OPEN", defaults={"name": "Открытый RFQ", "sort_order": 25})[0]
    draft_status = QuoteStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик", "sort_order": 10})[0]
    client = data["supplier"]
    deals = [Deal.objects.create(title=f"Заявка {n}", company=client, stage=stage) for n in (1, 2)]
    quotes = [
        Quote.objects.create(
            deal=deal, version=1, status=draft_status, seller_company=data["own"], total_incl_vat=Decimal("0")
        )
        for deal in deals
    ]
    draft = ProductStatus.objects.get(code="DRAFT")
    data["relay"].status = ProductStatus.objects.get(code="PUBLISHED")
    data["relay"].save()

    def candidate(name, demand, deal):
        return Product.objects.create(
            name=name, owner_company=data["own"], status=draft, source_deal=deal, demand_count=demand
        )

    relay_twin = candidate("реле защиты рз-1", 2, deals[0])
    sleeper = candidate("Шпала ЖБ", 1, deals[1])
    manual = Product.objects.create(name="Заведена руками", owner_company=data["own"], status=draft)
    for position, (quote, product) in enumerate(
        ((quotes[0], relay_twin), (quotes[1], relay_twin), (quotes[1], sleeper))
    ):
        QuoteItem.objects.create(
            quote=quote, position=position + 1, quantity=1, imported_raw_name=product.name, product=product
        )
    return {**data, "deals": deals, "relay_twin": relay_twin, "sleeper": sleeper, "manual": manual}


def test_queue_lists_request_drafts_most_asked_first(world):
    response = world["clients"]["manager"].get(URL, {"review": "requests"})
    assert response.status_code == 200, response.json()
    rows = response.json()["results"]
    assert [row["id"] for row in rows] == [world["relay_twin"].pk, world["sleeper"].pk]
    first = rows[0]
    assert first["demand"] == 2 and first["asked_total"] == 2
    assert set(first["asked_in"]) == {deal.number for deal in world["deals"]}
    assert first["duplicate"] == {
        "id": world["relay"].pk,
        "name": world["relay"].name,
        "sku": world["relay"].sku,
        "by": "name",
    }
    assert rows[1]["duplicate"] is None and isinstance(rows[1]["completeness"], int)


def test_merge_moves_lines_into_the_published_card(world):
    twin = world["relay_twin"]
    response = world["clients"]["supply"].post(f"{URL}{twin.pk}/merge/", {"into": world["relay"].pk}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["id"] == world["relay"].pk
    assert not QuoteItem.objects.filter(product=twin).exists()
    assert QuoteItem.objects.filter(product=world["relay"]).count() == 2
    twin.refresh_from_db()
    assert twin.status.code == "ARCHIVED"
    queue = world["clients"]["supply"].get(URL, {"review": "requests"}).json()["results"]
    assert [row["id"] for row in queue] == [world["sleeper"].pk]


def test_merge_needs_catalog_manage_and_another_card(world):
    twin = world["relay_twin"]
    refused = world["clients"]["manager"].post(f"{URL}{twin.pk}/merge/", {"into": world["relay"].pk}, format="json")
    assert refused.status_code == 403
    same = world["clients"]["supply"].post(f"{URL}{twin.pk}/merge/", {"into": twin.pk}, format="json")
    assert same.status_code == 400 and same.json()["detail"] == "MERGE_SAME_PRODUCT"

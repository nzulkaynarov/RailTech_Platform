"""ADR-0027: строка расчёта всегда связана с карточкой каталога — найденной или черновиком.

Владелец 2026-11-16: «раньше в erp была фича: позиции, которых нет в каталоге, заводились черновиком… в КП можно всё что
угодно записать?» Теперь черновик рождается, когда строка входит в расчёт, и строка ссылается на него.
"""

from __future__ import annotations

import pytest

from catalog.models import DomainType, Product, ProductStatus
from crm.tests.test_calc import ENGINEER, SUPPLY, _api, _staff, _url, world  # noqa: F401  # фикстура мира расчёта
from sales.models import QuoteItem

pytestmark = pytest.mark.django_db


@pytest.fixture
def catalog_lookups(db):
    for code, prefix in ((DomainType.GENERAL_GOODS, "RT"), (DomainType.SERVICES, "SV")):
        DomainType.objects.get_or_create(code=code, defaults={"name": code, "sku_prefix": prefix, "sort_order": 10})
    for code in ("DRAFT", "PUBLISHED"):
        ProductStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})


def _add(world, client, rows):  # noqa: F811
    response = client.post(_url(world, "lines/"), {"lines": rows}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()["created"]


def test_new_lines_get_draft_cards_of_their_type(world, catalog_lookups):  # noqa: F811
    supply, engineer = _api(world["supply"]), _api(world["engineer"])
    assert supply.post(_url(world, "start/")).status_code == 200
    [goods_id] = _add(world, supply, [{"name": "Рельс Р65", "quantity": 2}])
    [service_id] = _add(world, engineer, [{"name": "Логистика до станции", "kind": "service", "quantity": 1}])

    goods = QuoteItem.objects.select_related("product__status", "product__domain_type").get(pk=goods_id)
    service = QuoteItem.objects.select_related("product__status", "product__domain_type").get(pk=service_id)
    assert goods.product.status.code == "DRAFT" and goods.product.name == "Рельс Р65"
    assert goods.product.domain_type.code == DomainType.GENERAL_GOODS
    assert service.product.domain_type.code == DomainType.SERVICES
    assert service.product.sku.startswith(f"{service.product.domain_type.sku_prefix}-")
    assert goods.imported_raw_name == "Рельс Р65"  # слова строки не меняются

    lines = {line["id"]: line for line in supply.get(_url(world, "")).json()["lines"]}
    assert lines[goods_id]["product_id"] == goods.product_id
    assert lines[service_id]["zone"] == "services"


def test_same_name_matches_the_existing_card(world, catalog_lookups):  # noqa: F811
    supply = _api(world["supply"])
    assert supply.post(_url(world, "start/")).status_code == 200
    first, second = _add(world, supply, [{"name": "Шпала ЖБ"}, {"name": "шпала жб"}])
    a, b = QuoteItem.objects.get(pk=first), QuoteItem.objects.get(pk=second)
    assert a.product_id == b.product_id
    assert Product.objects.get(pk=a.product_id).demand_count == 2


def test_renaming_a_line_renames_its_own_draft(world, catalog_lookups):  # noqa: F811
    supply = _api(world["supply"])
    assert supply.post(_url(world, "start/")).status_code == 200
    [line_id] = _add(world, supply, [{"name": "рельсы"}])
    response = supply.patch(_url(world, f"lines/{line_id}/"), {"name": "Рельс Р65"}, format="json")
    assert response.status_code == 200, response.json()
    item = QuoteItem.objects.select_related("product").get(pk=line_id)
    assert item.product.name == "Рельс Р65"
    assert Product.objects.filter(source_deal=world["deal"]).count() == 1


def test_renaming_a_line_matched_to_a_shared_draft_relinks_it(world, catalog_lookups):  # noqa: F811
    supply = _api(world["supply"])
    assert supply.post(_url(world, "start/")).status_code == 200
    first, second = _add(world, supply, [{"name": "Болт"}, {"name": "болт"}])
    response = supply.patch(_url(world, f"lines/{second}/"), {"name": "Гайка М24"}, format="json")
    assert response.status_code == 200, response.json()
    a, b = QuoteItem.objects.select_related("product").get(pk=first), QuoteItem.objects.select_related("product").get(
        pk=second
    )
    assert a.product.name == "Болт" and a.product.demand_count == 1
    assert b.product.name == "Гайка М24" and b.product_id != a.product_id


def test_kind_of_own_draft_follows_the_line(world, catalog_lookups):  # noqa: F811
    both = _staff(
        world["seller"], "both@demo.test", sorted(set(SUPPLY) | set(ENGINEER))
    )  # смена типа — права обеих зон
    supply = _api(both)
    assert supply.post(_url(world, "start/")).status_code == 200
    [line_id] = _add(world, supply, [{"name": "Монтаж"}])
    response = supply.patch(_url(world, f"lines/{line_id}/"), {"kind": "service"}, format="json")
    assert response.status_code == 200, response.json()
    item = QuoteItem.objects.select_related("product__domain_type").get(pk=line_id)
    assert item.product.domain_type.code == DomainType.SERVICES


def test_kind_of_a_published_card_comes_from_the_catalog(world, catalog_lookups):  # noqa: F811
    supply = _api(world["supply"])
    assert supply.post(_url(world, "start/")).status_code == 200
    [line_id] = _add(world, supply, [{"name": "Подшипник"}])
    product = QuoteItem.objects.get(pk=line_id).product
    product.status = ProductStatus.objects.get(code="PUBLISHED")
    product.save()
    response = supply.patch(_url(world, f"lines/{line_id}/"), {"kind": "service"}, format="json")
    assert response.status_code == 400
    assert response.json()["detail"] == "KIND_FROM_CATALOG"


def test_matching_a_draft_line_to_the_catalog_drops_the_draft(world, catalog_lookups):  # noqa: F811
    supply = _api(world["supply"])
    assert supply.post(_url(world, "start/")).status_code == 200
    [line_id] = _add(world, supply, [{"name": "стрелочный перевод"}])
    draft_id = QuoteItem.objects.get(pk=line_id).product_id
    world["rail"].status = ProductStatus.objects.get(code="PUBLISHED")
    world["rail"].save()
    response = supply.patch(_url(world, f"lines/{line_id}/"), {"product_id": world["rail"].pk}, format="json")
    assert response.status_code == 200, response.json()
    line = next(line for line in response.json()["lines"] if line["id"] == line_id)
    assert line["product_id"] == world["rail"].pk and line["product_draft"] is False
    assert not Product.objects.filter(pk=draft_id).exists()

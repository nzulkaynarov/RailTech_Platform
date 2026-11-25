"""В-2 через настоящий путь расчёта: строка клиента (`add_lines`) получает карточку-черновик из слов клиента — партнёру
такая карточка и коды клиента (mpn, чертёж) не уходят, пока человек не подтвердит название."""

from __future__ import annotations

import pytest
from sales.models import QuoteItem
from supply.services import price_requests

from catalog.models import ProductStatus
from crm.tests.test_calc import _api, _url, world  # noqa: F401  # фикстура мира расчёта

pytestmark = pytest.mark.django_db

CLIENT_WORDS = "Стрелка для ст. Чиланзар, ООО МетроСтрой"
CLIENT_MPN = "МС-КОД-77"
CLIENT_DRAWING = "ЧЕРТ-МС-1234"


def _client_line(world):  # noqa: F811
    ProductStatus.objects.get_or_create(code="DRAFT", defaults={"name": "Черновик"})
    supply = _api(world["supply"])
    assert supply.post(_url(world, "start/")).status_code == 200
    response = supply.post(
        _url(world, "lines/"),
        {"lines": [{"name": CLIENT_WORDS, "quantity": 3, "article": CLIENT_MPN}]},
        format="json",
    )
    assert response.status_code == 201, response.json()
    item = QuoteItem.objects.get(imported_raw_name=CLIENT_WORDS)
    QuoteItem.objects.filter(pk=item.pk).update(gost_drawing=CLIENT_DRAWING)
    item.refresh_from_db()
    return item


def _preview(world, item, partner_names=None):  # noqa: F811
    """Строки так, как их увидит партнёр (`partner_lines` кормит и предпросмотр, и отправку запроса)."""
    fresh = QuoteItem.objects.select_related("product__status").get(pk=item.pk)
    rows = price_requests.partner_lines([fresh], partner_names)
    return {"lines": rows, "ready": all(r["name"] is not None for r in rows)}


def test_a_card_made_by_the_calculation_from_client_words_is_not_our_card(world):  # noqa: F811
    item = _client_line(world)
    assert item.product_id and item.product.status.code == "DRAFT"  # расчёт сам завёл карточку из слов клиента
    assert item.product.name == CLIENT_WORDS
    shown = _preview(world, item)
    row = shown["lines"][0]
    assert row["source"] == "missing" and row["name"] is None and shown["ready"] is False
    assert row["article"] == ""


def test_client_codes_never_become_the_partner_article(world):  # noqa: F811
    item = _client_line(world)
    assert item.mpn == CLIENT_MPN and item.gost_drawing == CLIENT_DRAWING
    confirmed = _preview(world, item, partner_names={item.pk: {"name": "Стрелочный перевод"}})
    row = confirmed["lines"][0]
    assert row["source"] == "staff" and row["name"] == "Стрелочный перевод"
    assert CLIENT_MPN not in row["article"] and CLIENT_DRAWING not in row["article"]
    # опубликованная карточка — наша: название и наш артикул, не коды клиента
    item.product.status = ProductStatus.objects.get_or_create(code="PUBLISHED", defaults={"name": "Опубликован"})[0]
    item.product.name = "Перевод стрелочный Р65 1/11"
    item.product.save()
    item.refresh_from_db()
    row = _preview(world, item)["lines"][0]
    assert row["source"] == "card" and row["name"] == "Перевод стрелочный Р65 1/11"
    assert CLIENT_MPN not in row["article"] and CLIENT_DRAWING not in row["article"]

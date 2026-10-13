"""Позиции КП принадлежат ОДНОМУ документу, а не сделке.

Найдено прогоном глазами 06-08. У сделки бывает несколько Quote: контейнер строк заявки
покупателя (`_request_draft_quote`, prepared_by=NULL) и КП продавца, созданное одной кнопкой
(W2). Билдер грузил позиции фильтром по СДЕЛКЕ, а фильтра по конкретному КП в API не
существовало вовсе — `?quote=24` молча игнорировался. Пока у сделки был один документ, это
совпадало; со вторым продавец увидел 4 строки вместо 2, половину — с нулевой ценой, и такое
КП можно было отправить клиенту.

Тесты держат обе половины: сервер умеет фильтровать по документу, и фильтр действительно
сужает выдачу.
"""

from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from crm.models import Quote, QuoteItem, QuoteStatus

pytestmark = pytest.mark.django_db


def _seller_client(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def two_quotes(scene):
    """Сцена W2 + КП продавца: у сделки ДВА документа, как в жизни."""
    draft = QuoteStatus.objects.get(code="DRAFT")
    seller_quote = Quote.objects.create(
        deal=scene["deal"],
        version=2,
        status=draft,
        prepared_by=scene["seller_user"],
        seller_company=scene["seller"],
    )
    QuoteItem.objects.create(
        quote=seller_quote,
        product=scene["product"],
        quantity=5,
        frozen_base_price=Decimal("120.00"),
    )
    return {**scene, "seller_quote": seller_quote}


def test_filter_by_quote_returns_only_that_document(two_quotes):
    """`?quote=<id>` отдаёт строки ТОЛЬКО этого КП — раньше параметр игнорировался."""
    client = _seller_client(two_quotes["seller_user"])

    response = client.get(f"/api/v1/crm/quote-items/?quote={two_quotes['seller_quote'].id}")

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1, "в КП продавца одна позиция — строки заявки покупателя сюда не относятся"
    assert rows[0]["quote"] == two_quotes["seller_quote"].id


def test_filter_by_deal_still_returns_every_document(two_quotes):
    """Контрольный: фильтр по сделке НЕ сломан — он просто отвечает на другой вопрос."""
    client = _seller_client(two_quotes["seller_user"])

    response = client.get(f"/api/v1/crm/quote-items/?quote__deal_id={two_quotes['deal'].id}")

    assert response.status_code == 200
    assert len(response.json()) == 3, "2 строки заявки + 1 строка КП продавца"


def test_request_container_and_seller_quote_do_not_bleed_into_each_other(two_quotes):
    """Суть дефекта: билдер, спросив свой КП, не должен увидеть строки заявки покупателя."""
    client = _seller_client(two_quotes["seller_user"])
    request_container = two_quotes["request_quote"]

    seller_rows = client.get(f"/api/v1/crm/quote-items/?quote={two_quotes['seller_quote'].id}").json()
    request_rows = client.get(f"/api/v1/crm/quote-items/?quote={request_container.id}").json()

    seller_ids = {row["id"] for row in seller_rows}
    request_ids = {row["id"] for row in request_rows}
    assert seller_ids and request_ids
    assert seller_ids.isdisjoint(request_ids), "документы не должны делить позиции"

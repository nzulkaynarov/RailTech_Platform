"""«Расчёт готов» по строкам без карточки каталога и валюта закупки (прод 2026-11-16, ЗВ-2026-002: «ERP не ответила»).

Новые строки расчёта берут валюту закупки из настроек компании (на проде — USD), а закупку вводили в сумах. На «Расчёт
готов» КП пересчитывается по сегодняшнему курсу: 2,3 млрд × 12 500 не влезает в поле суммы — было 500, теперь понятный
отказ 409 `AMOUNT_TOO_LARGE`; после смены валюты строки на UZS КП уходит директору.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from master_data.models import Currency, ExchangeRate

from crm.tests.test_calc import _api, _url, world  # noqa: F401  # фикстура мира расчёта

pytestmark = pytest.mark.django_db


def _lines(world):  # noqa: F811
    supply, engineer = _api(world["supply"]), _api(world["engineer"])
    assert supply.post(_url(world, "start/")).status_code == 200
    created = supply.post(
        _url(world, "lines/"),
        {"lines": [{"name": "тест товар", "quantity": 1}, {"name": "рельсы", "quantity": 1}]},
        format="json",
    )
    assert created.status_code == 201, created.json()
    service = engineer.post(
        _url(world, "lines/"), {"lines": [{"name": "логистика", "kind": "service", "quantity": 1}]}, format="json"
    )
    assert service.status_code == 201, service.json()
    return created.json()["created"], service.json()["created"][0]


def _price_and_sign(world, goods, service_id, currency):  # noqa: F811
    supply, engineer = _api(world["supply"]), _api(world["engineer"])
    for line_id, price in zip(goods, ("10000000", "2345330000")):
        body = {"purchase_price": price, "client_price": str(int(price) * 12 // 10)}
        if currency:
            body["purchase_currency"] = currency
        response = supply.patch(_url(world, f"lines/{line_id}/"), body, format="json")
        assert response.status_code == 200, response.json()
        assert supply.post(_url(world, f"lines/{line_id}/visa/")).status_code == 200
    response = engineer.patch(
        _url(world, f"lines/{service_id}/"),
        {"crew_rate": "1000000", "crew_days": "10", "client_price": "12000000"},
        format="json",
    )
    assert response.status_code == 200, response.json()
    assert engineer.post(_url(world, f"lines/{service_id}/visa/")).status_code == 200


def test_ready_with_free_text_lines_in_sums_goes_to_the_director(world):  # noqa: F811
    goods, service_id = _lines(world)
    _price_and_sign(world, goods, service_id, None)
    done = _api(world["supply"]).post(_url(world, "ready/"))
    assert done.status_code == 200, done.content[:2000]
    assert done.json()["quote"]["state"] == "at_director"


def test_sums_entered_on_usd_lines_are_a_clear_refusal_not_a_500(world):  # noqa: F811
    usd, _ = Currency.objects.get_or_create(code="USD", defaults={"name": "Доллар США", "sort_order": 20})
    goods, service_id = _lines(world)
    # Цены и визы — пока курса USD нет (пересчёт идёт с курсом 1, как было на проде), курс ЦБ приходит потом.
    _price_and_sign(world, goods, service_id, "USD")
    ExchangeRate.objects.create(
        currency=usd, rate_date=timezone.localdate() - timedelta(days=1), rate_to_uzs=Decimal("12500.00"), source="TEST"
    )
    refused = _api(world["supply"]).post(_url(world, "ready/"))
    assert refused.status_code == 409, refused.content[:2000]
    assert refused.json()["detail"] == "AMOUNT_TOO_LARGE"

    # Валюту строки поправили на сумы — КП уходит директору.
    for line_id in goods:
        fixed = _api(world["supply"]).patch(_url(world, f"lines/{line_id}/"), {"purchase_currency": "UZS"}, format="json")
        assert fixed.status_code == 200, fixed.json()
        assert _api(world["supply"]).post(_url(world, f"lines/{line_id}/visa/")).status_code == 200
    done = _api(world["supply"]).post(_url(world, "ready/"))
    assert done.status_code == 200, done.content[:2000]

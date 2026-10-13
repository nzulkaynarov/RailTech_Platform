"""Endpoint витрины платежей: гейты, коды ошибок и деградация вместо 500."""

import pytest

from master_data import customs_duties
from master_data.customs_duties import DutiesUnavailable
from master_data.models import HSCode

pytestmark = pytest.mark.django_db

URL = "/api/v1/master-data/hs-codes/{code}/duties/"

SAMPLE = {
    "payments": [{"code": "29", "source_label": "QQS", "rate": "12.00 %", "legal_basis": "ЗРУ-812"}],
    "permits": [],
}


@pytest.fixture
def hs_code():
    return HSCode.objects.create(code="8703101100", name="Автомобили легковые", level=10)


def test_requires_authentication(api_client, hs_code):
    response = api_client.get(URL.format(code=hs_code.code), {"origin": "CN"})
    assert response.status_code == 401


def test_returns_duties_for_a_known_code(authenticated_client, hs_code, monkeypatch):
    monkeypatch.setattr(
        customs_duties, "get_duties", lambda code, numeric: {**SAMPLE, "fetched_at": "now", "source_url": "u"}
    )

    response = authenticated_client.get(URL.format(code=hs_code.code), {"origin": "CN"})

    assert response.status_code == 200
    body = response.json()
    assert body["hs_code"] == hs_code.code
    assert body["origin"] == "CN"
    assert body["payments"][0]["rate"] == "12.00 %"
    # источник и время подписываются в ответе — интерфейс обязан их показать
    assert body["fetched_at"] and body["source_url"]


def test_unknown_code_is_404_not_a_query_to_the_source(authenticated_client, monkeypatch):
    """Произвольные цифры в чужой сервис не гоняем — сверяем по своему классификатору."""
    called = []
    monkeypatch.setattr(customs_duties, "get_duties", lambda code, numeric: called.append(code))

    response = authenticated_client.get(URL.format(code="9999999999"), {"origin": "CN"})

    assert response.status_code == 404
    assert response.json() == {"detail": "HS_CODE_UNKNOWN"}
    assert called == []


def test_origin_country_is_required(authenticated_client, hs_code):
    """Ставка без страны происхождения бессмысленна — преференции зависят именно от неё."""
    response = authenticated_client.get(URL.format(code=hs_code.code))
    assert response.status_code == 400
    assert response.json() == {"detail": "ORIGIN_COUNTRY_REQUIRED"}


def test_country_without_iso_numeric_is_rejected(authenticated_client, hs_code):
    """Строку, заведённую оператором вручную, тарифу не скормить — честная 400, не 500."""
    from master_data.models import Country

    Country.objects.create(code="XX", name="Особая территория", iso_numeric="")

    response = authenticated_client.get(URL.format(code=hs_code.code), {"origin": "XX"})
    assert response.status_code == 400
    assert response.json() == {"detail": "ORIGIN_COUNTRY_REQUIRED"}


def test_dead_source_degrades_to_503_with_a_code(authenticated_client, hs_code, monkeypatch):
    """Источник лёг — интерфейсу нужен КОД, чтобы показать ссылку на калькулятор ГТК."""

    def dead(code, numeric):
        raise DutiesUnavailable("источник лёг")

    monkeypatch.setattr(customs_duties, "get_duties", dead)

    response = authenticated_client.get(URL.format(code=hs_code.code), {"origin": "CN"})
    assert response.status_code == 503
    assert response.json() == {"detail": "HS_DUTIES_UNAVAILABLE"}

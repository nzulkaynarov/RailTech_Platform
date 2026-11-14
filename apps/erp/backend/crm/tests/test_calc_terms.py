"""Условия КП в расчёте (план 0.5, FR-16): оплата, срок действия и срок поставки задаются в черновике и видны клиенту."""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from accounts.models import CompanySettings
from crm.models import ActivityLog, Quote
from crm.services.documents.blank import quote_document_extras
from crm.tests.test_calc import _api, _priced, _sheet, _started, _url, world  # noqa: F401 — фикстура world

TERMS = "terms/"


def _settings(world, **values):  # noqa: F811
    CompanySettings.objects.update_or_create(company=world["seller"], defaults=values)


def test_new_draft_takes_payment_terms_and_validity_from_company_settings(world):  # noqa: F811
    _settings(world, default_payment_terms="50% предоплата, 50% по поставке", default_offer_validity_days=30)
    _started(world)
    terms = _sheet(world, world["supply"])["quote"]["terms"]
    assert terms["payment_terms"] == "50% предоплата, 50% по поставке"
    assert terms["valid_until"] == (timezone.localdate() + timedelta(days=30)).isoformat()
    assert terms["delivery_days"] is None and terms["delivery_note"] is None


def test_terms_are_set_in_the_draft_and_keep_line_visas(world):  # noqa: F811
    goods_id, _service_id = _priced(world)
    supply = _api(world["supply"])
    assert supply.post(_url(world, f"lines/{goods_id}/visa/")).status_code == 200
    until = (timezone.localdate() + timedelta(days=14)).isoformat()
    body = {
        "payment_terms": " 100% предоплата ",
        "valid_until": until,
        "delivery_days": 60,
        "delivery_note": "под заказ",
    }
    response = supply.patch(_url(world, TERMS), body, format="json")
    assert response.status_code == 200, response.json()
    terms = response.json()["quote"]["terms"]
    assert terms == {
        "payment_terms": "100% предоплата",
        "valid_until": until,
        "delivery_days": 60,
        "delivery_days_lines": terms["delivery_days_lines"],
        "delivery_note": "под заказ",
    }
    goods = next(line for line in response.json()["lines"] if line["id"] == goods_id)
    assert goods["visa"] is not None
    assert ActivityLog.objects.filter(event_code="calc.terms_updated").count() == 1

    # Пустой срок поставки — снова максимум по строкам; повтор без изменений журнал не пишет.
    cleared = supply.patch(_url(world, TERMS), {"delivery_days": None}, format="json").json()["quote"]["terms"]
    assert cleared["delivery_days"] is None
    supply.patch(_url(world, TERMS), {"delivery_days": None}, format="json")
    assert ActivityLog.objects.filter(event_code="calc.terms_updated").count() == 2


def test_terms_refusals(world):  # noqa: F811
    _started(world)
    supply = _api(world["supply"])
    past = (timezone.localdate() - timedelta(days=1)).isoformat()
    assert supply.patch(_url(world, TERMS), {"valid_until": past}, format="json").json() == {
        "detail": "VALID_UNTIL_IN_PAST"
    }
    assert supply.patch(_url(world, TERMS), {}, format="json").json() == {"detail": "NOTHING_TO_CHANGE"}
    negative = supply.patch(_url(world, TERMS), {"delivery_days": -1}, format="json")
    assert negative.status_code == 400 and negative.json()["detail"] == "VALIDATION_FAILED"
    denied = _api(world["accountant"]).patch(_url(world, TERMS), {"payment_terms": "x"}, format="json")
    assert denied.status_code == 403


def test_terms_are_locked_once_the_quote_is_with_the_director(world):  # noqa: F811
    goods_id, service_id = _priced(world)
    assert _api(world["supply"]).post(_url(world, f"lines/{goods_id}/visa/")).status_code == 200
    assert _api(world["engineer"]).post(_url(world, f"lines/{service_id}/visa/")).status_code == 200
    assert _api(world["engineer"]).post(_url(world, "ready/")).status_code == 200
    locked = _api(world["supply"]).patch(_url(world, TERMS), {"payment_terms": "x"}, format="json")
    assert locked.status_code == 409 and locked.json()["detail"] == "QUOTE_NOT_DRAFT"


def test_quote_document_prints_the_quote_payment_terms_over_the_company_default(world):  # noqa: F811
    _settings(world, default_payment_terms="100% предоплата")
    _started(world)
    _api(world["supply"]).patch(_url(world, TERMS), {"payment_terms": "отсрочка 30 дней"}, format="json")
    quote = Quote.objects.get(deal=world["deal"])
    rows = quote_document_extras(quote, world["seller"])["quote_terms"]
    assert any("отсрочка 30 дней" in str(row) for row in rows)
    assert not any("100% предоплата" in str(row) for row in rows)


def test_terms_endpoint_conforms_to_the_v1_schema(world):  # noqa: F811
    from core.tests.openapi_fixtures import conforms, sends

    _started(world)
    path = "/api/v1/calc/{deal_id}/terms/"
    body = {"payment_terms": "100% предоплата", "delivery_days": 30}
    sends(path, "patch", body)
    conforms(_api(world["supply"]).patch(_url(world, TERMS), body, format="json"), path, "patch", status=200)
    conforms(_api(world["supply"]).patch(_url(world, TERMS), {}, format="json"), path, "patch", status=400)

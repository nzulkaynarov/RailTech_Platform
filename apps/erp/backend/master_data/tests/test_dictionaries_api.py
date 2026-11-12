"""Справочники «Расчёта» общим ресурсом `/api/v1/dictionaries` (решение владельца 2026-11-11): тот же контракт, что у
EDS и CRM — каталог, строки, добавить с кодом, изменить на трёх языках, порядок, удалить использованное нельзя."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from master_data.models import Currency, UnitOfMeasure
from master_data.tests.test_lookup_delete_and_archive import _referenced_unit, operator  # noqa: F401

BASE = "/api/v1/dictionaries"


@pytest.fixture(autouse=True)
def _cache():
    cache.clear()
    yield
    cache.clear()


def _api(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


@pytest.mark.django_db
def test_catalog_lists_the_four_kinds_with_fields(operator):  # noqa: F811
    body = _api(operator).get(BASE).json()
    kinds = {d["kind"]: d for d in body["items"]}
    assert list(kinds) == ["countries", "currencies", "units", "delivery-basis"]
    assert kinds["currencies"]["codes"] == "given"
    assert [a["key"] for a in kinds["countries"]["attrs"]] == ["alpha3", "iso_numeric", "vat_rate"]
    assert {a["type"] for a in kinds["delivery-basis"]["attrs"]} == {"text", "boolean"}


@pytest.mark.django_db
def test_add_change_names_hide_and_reorder(operator):  # noqa: F811
    api = _api(operator)
    created = api.post(
        f"{BASE}/currencies",
        {"code": "kzt", "name": {"ru": "Тенге", "uz": "Tenge", "en": "Tenge"}, "attrs": {"symbol": "₸"}},
        format="json",
    )
    assert created.status_code == 201, created.content
    assert created.json()["code"] == "KZT" and created.json()["attrs"] == {"symbol": "₸", "iso_numeric": ""}
    again = api.post(f"{BASE}/currencies", {"code": "KZT", "name": {"ru": "Дубль"}}, format="json")
    assert again.status_code == 409 and again.json()["details"]["reason"] == "code_taken"

    changed = api.patch(f"{BASE}/currencies/KZT", {"name": {"en": "Kazakh tenge"}, "active": False}, format="json")
    assert changed.status_code == 200
    row = Currency.objects.get(code="KZT")
    assert (row.name, row.name_en, row.is_active) == ("Тенге", "Kazakh tenge", False)
    visible = [r["code"] for r in api.get(f"{BASE}/currencies").json()["items"]]
    everything = [r["code"] for r in api.get(f"{BASE}/currencies", {"include_hidden": "true"}).json()["items"]]
    assert "KZT" not in visible and "KZT" in everything

    codes = list(reversed(everything))
    ordered = api.put(f"{BASE}/currencies/order", {"codes": codes}, format="json")
    assert [r["code"] for r in ordered.json()["items"]] == codes
    bad = api.patch(f"{BASE}/countries/UZ", {"attrs": {"vat_rate": "много"}}, format="json")
    assert bad.status_code == 422 and bad.json()["details"]["fields"] == {"attrs.vat_rate": "invalid_value"}


@pytest.mark.django_db
def test_used_value_is_only_hidden_not_deleted(operator):  # noqa: F811
    unit = _referenced_unit(None)
    api = _api(operator)
    refused = api.delete(f"{BASE}/units/{unit.code}")
    assert refused.status_code == 409 and refused.json()["details"]["reason"] == "value_in_use"
    assert UnitOfMeasure.objects.filter(code=unit.code).exists()
    free = UnitOfMeasure.objects.create(code="FREE_U", name="Свободная", sort_order=999)
    assert api.delete(f"{BASE}/units/{free.code}").status_code == 204


@pytest.mark.django_db
def test_writes_need_settings_edit(db):
    from accounts.models import CustomUser

    plain = CustomUser.objects.create_user(email="plain@test.uz", username="plain", password="Probe1234!")
    api = _api(plain)
    assert api.get(f"{BASE}/units").status_code == 200
    assert api.post(f"{BASE}/units", {"code": "x", "name": {"ru": "X"}}, format="json").status_code == 403
    assert APIClient().get(BASE).status_code == 401

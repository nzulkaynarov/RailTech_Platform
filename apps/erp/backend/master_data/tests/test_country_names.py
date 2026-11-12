"""Страны на трёх языках из CLDR (план справочников, PR 6): у всех 249 стран есть названия ru, uz, en; ручные правки
не перетираются; новая страна по коду сразу получает недостающие названия; коды сверены с ISO 3166-1 по CLDR."""

import pytest
from babel import Locale
from rest_framework.test import APIClient

from master_data.country_names import babel_names, fill_all
from master_data.models import Country
from master_data.tests.test_lookup_delete_and_archive import operator  # noqa: F401

pytestmark = pytest.mark.django_db


def test_every_country_has_three_names_after_migrate():
    empty = Country.objects.filter(name="") | Country.objects.filter(name_uz="") | Country.objects.filter(name_en="")
    assert list(empty.values_list("code", flat=True)) == []
    uz = Country.objects.get(code="UZ")
    assert (uz.name, uz.name_uz, uz.name_en) == ("Узбекистан", "O‘zbekiston", "Uzbekistan")
    assert Country.objects.get(code="DE").name_uz == "Germaniya"
    assert not Country.objects.filter(name_uz__contains="ʻ").exists()


def test_codes_match_iso_3166_in_cldr():
    """Каждый код — страна ISO 3166-1 из CLDR; alpha-3 и цифровой код уникальны и правильной формы."""
    territories = Locale.parse("en").territories
    rows = list(Country.objects.values_list("code", "alpha2", "alpha3", "iso_numeric"))
    assert len(rows) == 249
    assert [code for code, *_ in rows if code not in territories] == []
    assert all(code == alpha2 and len(code) == 2 and code.isalpha() and code.isupper() for code, alpha2, *_ in rows)
    assert len({alpha3 for *_, alpha3, _ in rows}) == 249
    assert all(len(alpha3) == 3 and alpha3.isupper() for *_, alpha3, _ in rows)
    assert len({numeric for *_, numeric in rows}) == 249
    assert all(len(numeric) == 3 and numeric.isdigit() for *_, numeric in rows)


def test_manual_names_are_kept_and_only_empty_ones_are_filled():
    jp = Country.objects.get(code="JP")
    jp.name_uz, jp.name_en = "Yaponiya (qo‘lda)", ""
    jp.save(update_fields=["name_uz", "name_en"])
    assert fill_all(Country.objects.filter(code="JP")) == 1
    jp.refresh_from_db()
    assert (jp.name_uz, jp.name_en) == ("Yaponiya (qo‘lda)", "Japan")
    assert fill_all(Country.objects.all()) == 0


def test_new_country_by_code_gets_missing_names(operator):  # noqa: F811
    Country.objects.filter(code="AQ").delete()
    api = APIClient()
    api.force_authenticate(user=operator)
    created = api.post("/api/v1/dictionaries/countries", {"code": "aq", "name": {"ru": "Антарктида"}}, format="json")
    assert created.status_code == 201, created.content
    assert created.json()["name"] == {"ru": "Антарктида", "uz": "Antarktida", "en": "Antarctica"}
    typed = api.patch("/api/v1/dictionaries/countries/AQ", {"name": {"uz": "Antarktika"}}, format="json")
    assert typed.json()["name"]["uz"] == "Antarktika"


def test_unknown_code_has_no_names():
    assert babel_names("QQ") == {"ru": "", "uz": "", "en": ""}

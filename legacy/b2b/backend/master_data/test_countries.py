"""Справочник стран по ISO 3166-1: полнота сида, сохранность выверенных строк, честный НДС."""

import pytest

from master_data.models import Country

pytestmark = pytest.mark.django_db

# Полный перечень ISO 3166-1 на момент снимка (миграция 0015).
ISO_COUNTRY_COUNT = 249


def test_migration_seeds_the_whole_iso_list():
    """Rule 1: после migrate справочник наполнен — раньше страны сеял только dev-core_seed."""
    assert Country.objects.count() == ISO_COUNTRY_COUNT


@pytest.mark.parametrize(
    ("code", "alpha3", "numeric"),
    [("UZ", "UZB", "860"), ("RU", "RUS", "643"), ("CN", "CHN", "156"), ("JP", "JPN", "392")],
)
def test_iso_codes_are_filled(code, alpha3, numeric):
    """numeric — язык таможенных систем (ГТК принимает 860/643/156), alpha3 — документы."""
    country = Country.objects.get(code=code)
    assert country.alpha3 == alpha3
    assert country.iso_numeric == numeric
    assert country.alpha2 == code  # alpha2 дублирует канонический ключ и не расходится с ним


def test_curated_rows_keep_their_vat_and_name():
    """Выверенные владельцем строки сид не перетирает — иначе повторился бы баг миграции 0003."""
    uzbekistan = Country.objects.get(code="UZ")
    assert uzbekistan.name == "Узбекистан"
    assert uzbekistan.vat_rate is not None and float(uzbekistan.vat_rate) == 12.00
    assert float(Country.objects.get(code="RU").vat_rate) == 20.00


def test_unverified_countries_have_no_invented_vat():
    """Ставка НДС по миру неизвестна и хранится как NULL: выдуманные 12% хуже пустоты."""
    assert Country.objects.get(code="JP").vat_rate is None
    # Ставку имеют ТОЛЬКО выверенные строки первоначального сида.
    assert Country.objects.filter(vat_rate__isnull=False).count() == 7


def test_trade_partners_sort_above_the_rest():
    """Частые партнёры не тонут в перечне из 249 стран — их поднимает sort_order."""
    top = list(Country.objects.order_by("sort_order", "name").values_list("code", flat=True)[:7])
    assert top == ["UZ", "KZ", "RU", "CN", "DE", "TR", "IN"]
    assert Country.objects.get(code="JP").sort_order == 100


def test_reseed_is_idempotent_and_preserves_manual_edits():
    """Повторный прогон миграции ничего не задваивает и не откатывает правки оператора."""
    from master_data.migrations import __name__ as _  # noqa: F401  — пакет миграций существует

    edited = Country.objects.get(code="JP")
    edited.name = "Япония (правка оператора)"
    edited.vat_rate = 10
    edited.save(update_fields=["name", "vat_rate"])

    from importlib import import_module

    from django.apps import apps

    migration = import_module("master_data.migrations.0015_seed_iso_countries")
    migration.seed_countries(apps, None)

    assert Country.objects.count() == ISO_COUNTRY_COUNT
    edited.refresh_from_db()
    assert edited.name == "Япония (правка оператора)"
    assert float(edited.vat_rate) == 10

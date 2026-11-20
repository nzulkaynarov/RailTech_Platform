"""СЦ-10: единица, написанная текстом, узнаётся по справочнику; неизвестная или неоднозначная — не угадывается."""

import pytest

from core.models import UnitOfMeasure
from core.seeds.uom import seed_uom
from core.units import unit_key, unit_resolver

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def units(db):
    seed_uom()


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("т", "TNE"),
        ("Т.", "TNE"),
        (" тонн ", "TNE"),
        ("шт", "H87"),
        ("ШТ.", "H87"),
        ("pcs", "H87"),
        ("компл", "SET"),
        ("м²", "MTK"),
        ("м2", "MTK"),
        ("кг.", "KGM"),
        ("TNE", "TNE"),
        ("рейс", None),
        ("", None),
        (None, None),
    ],
)
def test_unit_text_maps_to_dictionary(text, code):
    found = unit_resolver()(text)
    assert (found[0] if found else None) == code


def test_label_is_the_dictionary_name():
    assert unit_resolver()("шт") == ("H87", "шт.")


def test_ambiguous_label_is_not_guessed():
    UnitOfMeasure.objects.create(code="ZZ1", name="ед", sort_order=900)
    UnitOfMeasure.objects.create(code="ZZ2", name="ЕД.", sort_order=901)
    assert unit_resolver()("ед") is None


def test_inactive_unit_is_not_used():
    UnitOfMeasure.objects.filter(code="TNE").update(is_active=False)
    assert unit_resolver()("т") is None


def test_long_code_is_skipped():
    UnitOfMeasure.objects.create(code="LONGCODE9", name="рейс", sort_order=902)
    assert unit_resolver()("рейс") is None


def test_dictionary_read_lazily(django_assert_num_queries):
    resolve = unit_resolver()
    with django_assert_num_queries(0):
        assert resolve("") is None


def test_unit_key_ignores_case_dots_spaces_and_superscript():
    assert unit_key("м²") == unit_key("М2") == "м2"
    assert unit_key("ШТ.") == "шт"

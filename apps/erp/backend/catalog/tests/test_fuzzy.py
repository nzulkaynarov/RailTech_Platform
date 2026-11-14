"""FR-26: транслитерация запроса для поиска товара с опечатками (без базы)."""

from catalog.fuzzy import to_cyrillic, to_latin, variants


def test_latin_query_gets_a_cyrillic_variant_and_back():
    assert to_cyrillic("strelochniy") == "стрелочний"
    assert to_cyrillic("g'ildirak") == "ғилдирак"
    assert to_cyrillic("o'q") == "ўқ"
    assert to_latin("Ғилдирак") == "g'ildirak"
    assert to_latin("щётка") == "shchyotka"


def test_variants_keep_the_query_first_and_skip_repeats():
    assert variants("  Болт  М12 ") == ["болт м12", "bolt m12"]
    assert variants("bolt") == ["bolt", "болт"]
    assert variants("12-34") == ["12-34"]

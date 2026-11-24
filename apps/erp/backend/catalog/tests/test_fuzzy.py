"""FR-26: транслитерация запроса для поиска товара с опечатками (без базы)."""

from catalog.fuzzy import to_cyrillic, to_latin, to_new_alphabet, to_old_alphabet, variants


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


def test_new_and_old_uzbek_alphabets_are_one_spelling():
    """Владелец 2026-11-17: ö ↔ oʻ/o', ğ ↔ gʻ/g', ş ↔ sh, ç ↔ ch — запрос в одном алфавите находит другой."""
    assert to_old_alphabet("özbek ğildirak şlang çek") == "o'zbek g'ildirak shlang chek"
    assert to_new_alphabet("oʻzbek g'ildirak shlang chek og‘iz") == "özbek ğildirak şlang çek oğiz"
    assert "o'zbek" in variants("özbek")
    assert "özbek" in variants("oʻzbek")
    assert "gʻildirak".replace("ʻ", "'") in variants("ğildirak")
    assert "ғилдирак" in variants("ğildirak")
    assert to_cyrillic("şartnoma çek") == "шартнома чек"
    assert "şartnoma" in variants("shartnoma") and "shartnoma" in variants("şartnoma")
    assert "chek" in variants("çek") and "çek" in variants("chek")
    assert "çek" in variants("чек")

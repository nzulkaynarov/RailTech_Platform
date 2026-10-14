"""Код ТН ВЭД от модели принимается, ТОЛЬКО если он был среди кандидатов справочника.

Даже с прямым запретом в промпте языковая модель может вернуть «похожий» код — а придуманный
ТН ВЭД хуже пустого: продавец узнает об ошибке на границе. Поэтому выбор модели проходит
ДЕТЕРМИНИРОВАННУЮ сверку со списком, который мы же ей и дали (retrieval → выбор → проверка).

Это тот самый приём, которым в проекте уже закрыты деньги: «числа ИИ для денег не
используются» — здесь то же правило применено к таможенному коду.
"""

import pytest
from ai.services.enrich import _accepted_hs_code

CANDIDATES = [
    {"code": "8482100000", "name": "Подшипники шариковые прочие"},
    {"code": "860721", "name": "Тормоза пневматические и их части"},
]


def test_choice_from_the_list_is_accepted():
    assert _accepted_hs_code("8482100000", CANDIDATES) == "8482100000"


def test_invented_code_is_rejected_even_if_it_looks_plausible():
    """«8482100001» отличается одной цифрой — и это уже другой товар."""
    assert _accepted_hs_code("8482100001", CANDIDATES) == ""


def test_separators_inside_the_code_do_not_break_the_match():
    assert _accepted_hs_code("8482 10 0000", CANDIDATES) == "8482100000"


def test_empty_answer_stays_empty():
    assert _accepted_hs_code("", CANDIDATES) == ""
    assert _accepted_hs_code(None, CANDIDATES) == ""


def test_without_candidates_nothing_is_accepted():
    """Справочник пуст → кандидатов нет → любой код модели отвергается."""
    assert _accepted_hs_code("8482100000", []) == ""


@pytest.mark.django_db
def test_enrichment_is_neutral_when_ai_is_off(settings):
    """AI выключен — обогащение молчит и не ломает создание карточки."""
    from catalog.ai_enrich import enrich_product

    settings.AI_IMPORT_ENABLED = False

    assert enrich_product("Подшипник буксовый") == {}

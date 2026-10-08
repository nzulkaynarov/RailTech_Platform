"""Схема golden-кейсов: все YAML валидны, id уникальны, покрытие категорий Фазы 2."""

from collections import Counter

from evals.golden import load_cases


def test_golden_cases_are_valid_and_unique() -> None:
    cases = load_cases()
    assert len(cases) >= 15
    counts = Counter(c.id for c in cases)
    assert [i for i, n in counts.items() if n > 1] == []


def test_phase2_categories_and_languages_are_covered() -> None:
    cases = load_cases()
    categories = {c.category for c in cases}
    assert {"kb_answer", "not_in_kb", "injection", "smalltalk"} <= categories
    kb_languages = {c.language for c in cases if c.category == "kb_answer"}
    assert kb_languages == {"ru", "uz", "en"}


def test_qualifier_cases_are_valid() -> None:
    from evals.qualifier_cases import load_qualifier_cases

    cases = load_qualifier_cases()
    assert len(cases) >= 30
    assert len({c.id for c in cases}) == len(cases)
    assert sum(c.expect.escalate for c in cases) >= 10


def test_customer_cases_present() -> None:
    cases = [c for c in load_cases() if c.mode == "customer"]
    assert len(cases) >= 10
    assert {"deliver_document", "handoff", "answer"} <= {a for c in cases for a in c.expect.actions}

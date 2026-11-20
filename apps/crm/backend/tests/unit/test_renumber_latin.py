"""Перенумерация в латиницу (СЦ-5): разбор маппинга и замена номеров в тексте."""

import pytest

from app.services.renumber_latin import parse_mapping, replace_numbers

MAPPING = {"ВХ-001/26": "IN-001/26", "ЗВ-2026-002": "PRJ-2026-002", "ОБР-0012": "TK-0012"}


def test_parse_mapping_reads_flat_object() -> None:
    assert parse_mapping('{"ВХ-001/26": "IN-001/26"}') == {"ВХ-001/26": "IN-001/26"}


@pytest.mark.parametrize(
    "raw",
    ["[]", '{"a": 1}', '{"": "X"}', '{"A-1": "A-1"}', '{"A-1": " "}', "not json"],
)
def test_parse_mapping_rejects_bad_input(raw: str) -> None:
    with pytest.raises(ValueError):  # noqa: PT011 — JSONDecodeError is a ValueError too
        parse_mapping(raw)


def test_replace_numbers_in_text() -> None:
    text = "Письмо ВХ-001/26 привязано к ЗВ-2026-002, обращение ОБР-0012."
    assert replace_numbers(text, MAPPING) == (
        "Письмо IN-001/26 привязано к PRJ-2026-002, обращение TK-0012."
    )


def test_replace_does_not_touch_longer_numbers() -> None:
    """`ВХ-001/26` не совпадает внутри `ВХ-001/260` и `ЗВ-2026-0020`."""
    text = "ВХ-001/260, ЗВ-2026-0020, ОБР-00123"
    assert replace_numbers(text, MAPPING) == text


def test_replace_is_single_pass_and_idempotent() -> None:
    chained = {"A-1": "B-1", "B-1": "C-1"}
    assert replace_numbers("A-1 B-1", chained) == "B-1 C-1"
    once = replace_numbers("Письмо ВХ-001/26", MAPPING)
    assert replace_numbers(once, MAPPING) == once


def test_empty_mapping_changes_nothing() -> None:
    assert replace_numbers("ВХ-001/26", {}) == "ВХ-001/26"

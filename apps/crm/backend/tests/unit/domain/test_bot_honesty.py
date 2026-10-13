"""Тон и честность ответов бота (аудит 2026-10-12): решения кода без модели."""

import pytest

from app.domain.dialog_policy import Action, DecisionInput, decide, is_ack
from app.domain.stages import OwnerMode, Stage
from app.domain.text import drop_trailing_question, staff_name


def _input(**overrides: object) -> DecisionInput:
    base: dict[str, object] = {
        "owner_mode": OwnerMode.BOT,
        "stage": Stage.ENGAGED,
        "text": "Что входит в тариф Старт?",
        "human_requested": False,
        "stop_word_hit": False,
        "best_score": None,
        "min_score": 0.7,
        "need_known": True,
        "kb_unavailable": True,
    }
    base.update(overrides)
    return DecisionInput(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("overrides", "action", "reason"),
    [
        ({}, Action.FALLBACK, "kb_unavailable"),
        ({"text": "Привет"}, Action.ANSWER, "smalltalk"),
        ({"text": "Спасибо!"}, Action.ANSWER, "ack"),
        ({"customer": True}, Action.ANSWER, "customer_service"),
        ({"human_requested": True}, Action.HANDOFF, "human_requested"),
        ({"kb_unavailable": False, "best_score": 0.2}, Action.FALLBACK, "best_score=0.2 < 0.7"),
    ],
)
def test_decide_when_kb_is_unavailable(
    overrides: dict[str, object], action: Action, reason: str
) -> None:
    decision = decide(_input(**overrides))
    assert (decision.action, decision.reason) == (action, reason)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Спасибо!", True),
        ("ок", True),
        ("Понятно.", True),
        ("katta rahmat", True),
        ("Thank you", True),
        ("got it", True),
        ("Привет", False),
        ("Спасибо, а сколько стоит?", False),
        ("Понятно, спасибо", True),
        ("Thank you so much", True),
        ("it", False),
    ],
)
def test_is_ack(text: str, expected: bool) -> None:
    assert is_ack(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Тариф включает кассу. Сколько у вас точек?", "Тариф включает кассу."),
        ("Да. Подходит? Нужна доставка?", "Да."),
        ("Сколько у вас точек?", "Сколько у вас точек?"),
        ("Тариф включает кассу.", "Тариф включает кассу."),
        ("Что такое ОФД? Это оператор данных.", "Что такое ОФД? Это оператор данных."),
    ],
)
def test_drop_trailing_question(text: str, expected: str) -> None:
    assert drop_trailing_question(text) == expected


@pytest.mark.parametrize(
    ("full_name", "language", "expected"),
    [
        ("Азиз Каримов", "ru", "Азиз Каримов"),
        ("  Dilnoza   Yusupova ", "uz", "Dilnoza Yusupova"),
        ("Admin", "ru", "менеджер"),
        ("Test Manager", "en", "A manager"),
        ("manager2", "uz", "menejer"),
        ("ops@railtech.uz", "ru", "менеджер"),
        ("", "ru", "менеджер"),
        ("Тестовый Бот", "ru", "менеджер"),
    ],
)
def test_staff_name_for_client(full_name: str, language: str, expected: str) -> None:
    assert staff_name(full_name, language) == expected

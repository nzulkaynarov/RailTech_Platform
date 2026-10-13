"""Словарь канала команды: метки совпадают с CRM, коды не утекают (дизайн-аудит 2026-10-11)."""

import pytest

from app.bot.channel import _rejected
from app.domain.errors import ConflictError, DomainError, NotFoundError, Reason
from app.domain.stages import Stage
from app.domain.triggers import TriggerCode
from app.services import channel_texts as tx


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, "1 раз"), (2, "2 раза"), (4, "4 раза"), (5, "5 раз"), (12, "12 раз"), (22, "22 раза")],
)
def test_times(n: int, expected: str) -> None:
    assert tx.times(n) == expected


@pytest.mark.parametrize(
    ("code", "streak", "expected"),
    [
        ("kb_gap_streak", 2, "Бот не нашёл ответ 2 раза подряд"),
        ("kb_gap_streak", 5, "Бот не нашёл ответ 5 раз подряд"),
        ("kb_gap_streak", 1, "Бот не нашёл ответ"),
        ("high_score", 2, "Высокая оценка"),
        ("something_new", 2, "something_new"),
    ],
)
def test_reason(code: str, streak: int, expected: str) -> None:
    assert tx.reason(code, streak) == expected


def test_every_stage_has_a_label() -> None:
    assert {s.value for s in Stage} <= set(tx.STAGE)
    assert tx.stage("handoff") == "Передан"  # Q-015


def test_every_trigger_has_a_reason() -> None:
    assert {c.value for c in TriggerCode} <= set(tx.REASONS)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            ConflictError("x", reason=Reason.LEAD_TAKEN, assigned_user_name="Дилшод"),
            "Лида уже забрал Дилшод.",
        ),
        (ConflictError("x", reason=Reason.LEAD_TAKEN), "Лида уже забрал другой менеджер."),
        (NotFoundError("x"), "Лид не найден — возможно, клиент удалил переписку."),
        (DomainError("x"), "Не получилось забрать лида. Откройте карточку в CRM."),
    ],
)
def test_take_rejection_in_channel(error: DomainError, expected: str) -> None:
    assert _rejected(error) == expected

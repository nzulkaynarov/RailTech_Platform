"""Номер перед передачей по просьбе лида (решение владельца 2026-10-12) — таблица кейсов."""

import pytest

from app.domain.handoff_gate import TriggerSource, needs_phone_first


@pytest.mark.parametrize(
    ("required", "source", "has_phone", "is_client", "owner_mode", "consent", "expected"),
    [
        (True, "lead", False, False, "bot", True, True),  # главный случай: сначала номер
        (False, "lead", False, False, "bot", True, False),  # настройка выключена — как раньше
        (True, "system", False, False, "bot", True, False),  # сигнал бота — передаём сразу
        (True, "lead", True, False, "bot", True, False),  # номер уже есть
        (True, "lead", False, True, "bot", True, False),  # подтверждённый клиент
        (True, "lead", False, False, "paused", True, False),  # уже ждёт менеджера
        (True, "lead", False, False, "human", True, False),  # ведёт менеджер
        (True, "lead", False, False, None, True, False),  # лида ещё нет
        (True, "lead", False, False, "bot", False, False),  # сначала согласие
        (False, "system", True, True, "bot", True, False),
    ],
)
def test_needs_phone_first(
    required: bool,
    source: TriggerSource,
    has_phone: bool,
    is_client: bool,
    owner_mode: str | None,
    consent: bool,
    expected: bool,
) -> None:
    assert (
        needs_phone_first(
            required=required,
            source=source,
            has_phone=has_phone,
            is_client=is_client,
            owner_mode=owner_mode,
            consent_given=consent,
        )
        is expected
    )

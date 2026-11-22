"""Какой переключатель профиля ведает Telegram по виду уведомления EDS (ГЛ-2)."""

import pytest

from app.services.eds_notices import telegram_class


@pytest.mark.parametrize(
    "kind",
    [
        "extension_requested",  # продлить или отклонить срок поручения — решение, как и до ГЛ-2
        "approve_quote",
        "resolve_letter",
        "approve_memo",
        "pay_memo",
        "sign_commercial",
        "visa_commercial",
        "letter_sign_requested",
    ],
)
def test_decisions_follow_notify_decisions(kind: str) -> None:
    assert telegram_class(kind) == "decisions"


@pytest.mark.parametrize("kind", ["instruction_assigned", "instruction_overdue", "letter_executed"])
def test_other_tasks_follow_notify_tasks(kind: str) -> None:
    assert telegram_class(kind) == "tasks"


def test_rework_is_bell_only() -> None:
    assert telegram_class("rework_document") is None

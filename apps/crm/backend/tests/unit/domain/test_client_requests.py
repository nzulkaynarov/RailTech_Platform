"""«Создать заявку» и статус лида для Платформы (CRM-02, CRM-03, W16-D1-2): таблицы кейсов."""

import pytest

from app.domain.client_requests import (
    PlatformStatus,
    contact_channels,
    may_create_request,
    platform_status,
)
from app.domain.stages import Stage as S

P = PlatformStatus


@pytest.mark.parametrize(
    ("stage", "asks_price", "sla_overdue", "expected"),
    [
        (S.NEW, False, False, P.NEW),
        (S.NEW, True, True, P.NEW),
        (S.ENGAGED, False, False, P.DIALOG),
        (S.QUALIFIED, True, False, P.DIALOG),  # «просит цену» — только у передачи менеджеру
        (S.HANDOFF, False, False, P.DIALOG),
        (S.HANDOFF, True, False, P.WANTS_QUOTE),
        (S.HANDOFF, True, True, P.WANTS_QUOTE),  # просьба о КП важнее просрочки
        (S.HANDOFF, False, True, P.NO_ANSWER),
        (S.IN_PROGRESS, True, False, P.WANTS_QUOTE),
        (S.IN_PROGRESS, False, True, P.DIALOG),
        (S.UNRESPONSIVE, False, False, P.NO_ANSWER),
        (S.WON, False, False, P.CLIENT),
        (S.CUSTOMER, True, True, P.CLIENT),
        (S.LOST, True, False, P.LOST),
    ],
)
def test_platform_status(stage: S, asks_price: bool, sla_overdue: bool, expected: P) -> None:
    assert platform_status(stage, asks_price=asks_price, sla_overdue=sla_overdue) == expected


@pytest.mark.parametrize(
    ("stage", "allowed"),
    [
        (S.NEW, True),
        (S.ENGAGED, True),
        (S.QUALIFIED, True),
        (S.HANDOFF, True),
        (S.IN_PROGRESS, True),
        (S.UNRESPONSIVE, True),
        (S.WON, True),
        (S.CUSTOMER, True),  # новая заявка клиента
        (S.LOST, False),
    ],
)
def test_request_from_any_active_stage(stage: S, allowed: bool) -> None:
    assert may_create_request(stage) is allowed


@pytest.mark.parametrize(
    ("phone", "email", "telegram", "expected"),
    [
        (None, None, True, ["telegram"]),
        ("+998901234567", None, False, ["phone"]),  # e-mail не обязателен
        (None, "a@b.uz", False, ["email"]),
        ("+998901234567", "a@b.uz", True, ["telegram", "phone", "email"]),
        ("", "", False, []),
    ],
)
def test_contact_channels(
    phone: str | None, email: str | None, telegram: bool, expected: list[str]
) -> None:
    assert contact_channels(phone=phone, email=email, telegram=telegram) == expected

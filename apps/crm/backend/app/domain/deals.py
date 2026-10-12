"""Сделка: допустимые переходы стадий и итог при закрытии лида (ADR-0019, Q-013).

Чистые функции без I/O. Стадии сделки — `open` / `won` / `lost`; воронка лида остаётся
прежней (ADR-0015), сделка лишь фиксирует продукт, сумму и причину итога.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


class DealStage(StrEnum):
    OPEN = "open"
    WON = "won"
    LOST = "lost"


# Причина «Другое» — всегда допустима: ею помечается отказ без причины из справочника.
OTHER_REASON: Final = "Другое"


def may_transition(current: DealStage, target: DealStage, *, is_admin: bool) -> bool:
    """open→won/lost, lost→open/won (переоткрыть); won — финал, менять может только админ."""
    if current == target:
        return True
    if current == DealStage.WON:
        return is_admin
    return True


def lost_reason(code: str | None, dictionary: list[str]) -> str:
    """Причина отказа: значение из справочника «Настроек», иначе «Другое»."""
    value = (code or "").strip()
    return value if value in dictionary else OTHER_REASON


@dataclass(frozen=True, slots=True)
class OutcomePlan:
    """Что сделать со сделкой лида при закрытии лида (ADR-0019 «Связь с лидом»)."""

    create: bool
    stage: DealStage
    lost_reason: str | None


def plan_lead_outcome(
    outcome: str, has_open_deal: bool, reason_code: str | None, dictionary: list[str]
) -> OutcomePlan | None:
    """Выигрыш: закрыть открытую сделку или создать выигранную. Отказ: закрыть открытую.

    Отказ без открытой сделки — сделку не создаём (`None`): терять было нечего.
    """
    if outcome == DealStage.WON:
        return OutcomePlan(create=not has_open_deal, stage=DealStage.WON, lost_reason=None)
    if not has_open_deal:
        return None
    return OutcomePlan(
        create=False, stage=DealStage.LOST, lost_reason=lost_reason(reason_code, dictionary)
    )

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


def may_edit(current: DealStage, *, is_admin: bool) -> bool:
    """Любое изменение выигранной сделки (сумма, валюта, владелец, название) — только админ."""
    return current != DealStage.WON or is_admin


TITLE_MAX: Final = 255


def deal_title(
    *, client_name: str | None, lead_name: str | None, product_name: str | None, lead_id: int
) -> str:
    """Название сделки «<Клиент или имя лида> — <продукт>» (аудит 2026-10-12, P1-5).

    То же правило — в SQL миграции `0017_deal_titles` (бэкфилл), держать синхронно.
    """
    who = (client_name or "").strip() or (lead_name or "").strip() or f"Лид #{lead_id}"
    product = (product_name or "").strip()
    return (f"{who} — {product}" if product else who)[:TITLE_MAX]


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
) -> OutcomePlan:
    """Выигрыш: закрыть открытую сделку или создать выигранную. Отказ: закрыть открытую
    или создать проигранную с причиной (Q-021) — иначе аналитика отказов пуста."""
    if outcome == DealStage.WON:
        return OutcomePlan(create=not has_open_deal, stage=DealStage.WON, lost_reason=None)
    return OutcomePlan(
        create=not has_open_deal,
        stage=DealStage.LOST,
        lost_reason=lost_reason(reason_code, dictionary),
    )


@dataclass(frozen=True, slots=True)
class ErpOutcome:
    """Что сделать с зеркалом сделки по событию ERP (ADR-0022, CONTRACTS §3)."""

    stage: DealStage
    changed: bool
    lost_reason: str | None


def plan_erp_outcome(event: str, current: DealStage, lost_reason_text: str | None) -> ErpOutcome:
    """`deal.won` → `won`, `deal.lost` → `lost` с причиной текстом ERP (без справочника CRM).

    ERP — источник истины для зеркала: `won` не финал для ERP (переоткрытие там возможно),
    повтор того же события ничего не меняет. Стадия лида этим не затрагивается.
    """
    if event not in ("deal.won", "deal.lost"):
        raise ValueError(f"not a deal outcome event: {event}")
    if event == "deal.won":
        return ErpOutcome(stage=DealStage.WON, changed=current != DealStage.WON, lost_reason=None)
    reason = (lost_reason_text or "").strip() or OTHER_REASON
    return ErpOutcome(stage=DealStage.LOST, changed=current != DealStage.LOST, lost_reason=reason)

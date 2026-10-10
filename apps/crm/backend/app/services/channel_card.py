"""Текст и кнопки карточки лида в канале команды (SPEC §9.1). Чистые функции.

Формулировки — из словаря `channel_texts` (те же метки, что в CRM).
"""

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Final
from zoneinfo import ZoneInfo

from app.services import channel_texts as tx

TAKE_PREFIX: Final = "take:"
LAST_MAX: Final = 200


@dataclass(frozen=True, slots=True)
class CardData:
    lead_id: int
    display_name: str
    language: str
    score: int
    stage: str
    need_summary: str | None
    product_interest: list[str]
    timeline: str | None
    decision_role: str | None
    priority: str
    reason_codes: list[str]
    reason_text: str | None
    recommendation: str | None
    status: str
    taken_by: str | None
    taken_at: datetime | None
    sla_overdue: bool
    last_lead_message: str | None
    crm_url: str
    timezone: str = "Asia/Tashkent"
    kb_gap_streak: int = 2  # порог из настроек `escalation.kb_gap_streak`


def render(card: CardData) -> str:
    icon = tx.PRIORITY_ICON.get(card.priority, "")
    name = escape(card.display_name or tx.NO_NAME)
    title = tx.LEAD_TITLE.format(lead_id=card.lead_id)
    lines = [
        f"{icon} <b>{title}</b> · {name} · {card.language.upper()} · "
        f"{tx.SCORE.format(score=card.score)} · {tx.stage(card.stage)}",
    ]
    if card.need_summary:
        lines.append(tx.NEED.format(text=escape(card.need_summary)))
    lines.append(" · ".join(_details(card)))
    why = "; ".join(tx.reason(code, card.kb_gap_streak) for code in card.reason_codes)
    if card.reason_text:
        why = f"{why}; {card.reason_text}" if why else card.reason_text
    lines.append(tx.WHY.format(text=escape(why)))
    if card.recommendation:
        lines.append(tx.RECOMMENDATION.format(text=escape(card.recommendation)))
    if card.last_lead_message:
        last = card.last_lead_message.strip().replace("\n", " ")[:LAST_MAX]
        lines.append(tx.LAST_MESSAGE.format(text=escape(last)))
    if not card.crm_url.startswith("https://"):
        lines.append(tx.CRM_LINK.format(url=escape(card.crm_url)))
    lines.append(_status_line(card))
    return "\n".join(line for line in lines if line)


def _details(card: CardData) -> list[str]:
    details = []
    if card.product_interest:
        details.append(tx.INTEREST.format(text=escape(", ".join(card.product_interest))))
    if card.timeline:
        timeline = tx.TIMELINES.get(card.timeline, card.timeline)
        details.append(tx.TIMELINE.format(text=escape(timeline)))
    if card.decision_role:
        role = tx.ROLES.get(card.decision_role, card.decision_role)
        details.append(tx.ROLE.format(text=escape(role)))
    return details


def _status_line(card: CardData) -> str:
    local = ZoneInfo(card.timezone)
    if card.status == "taken" and card.taken_by:
        at = card.taken_at.astimezone(local).strftime("%H:%M") if card.taken_at else ""
        return tx.TAKEN_BY.format(name=escape(card.taken_by), at=at)
    if card.status == "snoozed":
        return tx.SNOOZED
    if card.status in ("returned", "closed"):
        return tx.CLOSED if card.status == "closed" else tx.RETURNED
    return tx.SLA_OVERDUE if card.sla_overdue else ""


def can_take(card: CardData) -> bool:
    return card.status in ("open", "snoozed")

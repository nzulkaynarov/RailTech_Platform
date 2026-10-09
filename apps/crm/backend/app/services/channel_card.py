"""Текст и кнопки карточки лида в канале команды (SPEC §9.1). Чистые функции."""

from dataclasses import dataclass
from datetime import datetime
from html import escape
from typing import Final
from zoneinfo import ZoneInfo

TAKE_PREFIX: Final = "take:"
PRIORITY_ICON: Final = {"hot": "🔥", "warm": "🟠", "info": "ℹ️"}
REASONS: Final = {
    "human_requested": "просит человека",
    "callback_requested": "просит звонок",
    "price_or_contract_asked": "спросил цену/условия — нет в базе",
    "negative_sentiment": "негатив",
    "complaint": "жалоба",
    "kb_gap_streak": "бот дважды не нашёл ответ",
    "no_progress": "диалог без прогресса",
    "competitor_mentioned": "упомянул конкурента",
    "high_score": "высокий score",
    "qualifier_recommend": "квалификатор рекомендует",
    "document_not_found": "документ не найден",
    "service_request": "сервисный запрос",
    "attachment_received": "прислал файл",
    "agent_unavailable": "сбой ИИ-ассистента — ответ не отправлен",
    "delivery_failed": "не удалось отправить файл клиенту",
}
TIMELINES: Final = {"<1m": "<1 мес", "<3m": "<3 мес", "<12m": "<12 мес", ">12m": ">12 мес"}
ROLES: Final = {"decision_maker": "ЛПР", "influencer": "влияет", "researcher": "изучает"}
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


def render(card: CardData) -> str:
    icon = PRIORITY_ICON.get(card.priority, "")
    name = escape(card.display_name or "без имени")
    lines = [
        f"{icon} <b>Лид #{card.lead_id}</b> · {name} · {card.language.upper()} · "
        f"Score {card.score} · {card.stage}",
    ]
    if card.need_summary:
        lines.append(f"Потребность: {escape(card.need_summary)}")
    details = [
        f"Интерес: {escape(', '.join(card.product_interest))}" if card.product_interest else "",
        f"Срок: {escape(TIMELINES.get(card.timeline or '', ''))}" if card.timeline else "",
        f"Роль: {ROLES.get(card.decision_role or '', '')}" if card.decision_role else "",
    ]
    if any(details):
        lines.append(" · ".join(d for d in details if d))
    why = "; ".join(REASONS.get(code, code) for code in card.reason_codes)
    if card.reason_text:
        why = f"{why}; {card.reason_text}" if why else card.reason_text
    lines.append(f"Почему: {escape(why)}")
    if card.recommendation:
        lines.append(f"Рекомендация: {escape(card.recommendation)}")
    if card.last_lead_message:
        last = card.last_lead_message.strip().replace("\n", " ")[:LAST_MAX]
        lines.append(f"Последнее: 👤 «{escape(last)}»")
    if not card.crm_url.startswith("https://"):
        lines.append(f"CRM: {escape(card.crm_url)}")
    lines.append(_status_line(card))
    return "\n".join(line for line in lines if line)


def _status_line(card: CardData) -> str:
    local = ZoneInfo(card.timezone)
    if card.status == "taken" and card.taken_by:
        at = card.taken_at.astimezone(local).strftime("%H:%M") if card.taken_at else ""
        return f"✅ Взял: {escape(card.taken_by)} · {at}"
    if card.status == "snoozed":
        return "💤 Отложено"
    if card.status in ("returned", "closed"):
        return "☑️ Закрыто" if card.status == "closed" else "🤖 Возвращён боту"
    return "⏰ <b>SLA просрочен</b>" if card.sla_overdue else ""


def can_take(card: CardData) -> bool:
    return card.status in ("open", "snoozed")

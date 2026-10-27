"""Текст и кнопки карточки лида в канале команды (SPEC §9.1). Чистые функции.

Формулировки — из словаря `channel_texts` (те же метки, что в CRM). В карточке нет сырых
кодов: продукты — названиями из справочника, время — в часовом поясе из настроек.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Final
from zoneinfo import ZoneInfo

from app.services import channel_texts as tx

# Новые карточки: `take:e<id эскалации>`. Старые `take:<id лида>` бот понимает как устаревшие.
TAKE_PREFIX: Final = "take:"
TAKE_ESCALATION: Final = "e"
LAST_MAX: Final = 200
# Приоритеты по важности: сводка и выбор «кого упоминать» идут в этом порядке.
PRIORITY_RANK: Final[dict[str, int]] = {"hot": 0, "warm": 1, "info": 2}
# Info-передачи — сигналы: бот продолжает отвечать, срока реакции и упоминаний нет.
SLA_PRIORITIES: Final = frozenset({"hot", "warm"})
# Причины, по которым карточка в канал не публикуется. Сейчас таких нет: передача клиента менеджеру
# из-за сбоя ИИ (`agent_unavailable`) — рабочая карточка (менеджер должен забрать клиента), а
# системный сигнал о сбое — строка «Ответы ИИ клиентам» центра внешних сервисов (W15-H3b).
SILENT_REASONS: Final[frozenset[str]] = frozenset()


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
    created_at: datetime | None = None
    now: datetime | None = None
    snoozed_until: datetime | None = None
    snoozed_by: str | None = None
    # Названия продуктов из справочника `products`; ключа нет в справочнике — не показываем.
    product_names: Mapping[str, str] | None = None
    escalation_id: int = 0  # для кнопки `take:e<id>`
    # Номер из Telegram (`telegram_identities.phone_e164`); нет — «Номер: не указан».
    phone: str | None = None


def render(card: CardData) -> str:
    icon = tx.PRIORITY_ICON.get(card.priority, "")
    name = escape(card.display_name or tx.NO_NAME)
    title = tx.LEAD_TITLE.format(lead_id=card.lead_id)
    lines = [
        f"{icon} <b>{title}</b> · {name} · {card.language.upper()} · "
        f"{tx.SCORE.format(score=card.score)} · {tx.stage(card.stage)}",
    ]
    lines.append(tx.PHONE.format(phone=escape(card.phone)) if card.phone else tx.PHONE_MISSING)
    if card.need_summary:
        lines.append(tx.NEED.format(text=escape(card.need_summary)))
    lines.append(" · ".join(_details(card)))
    lines.append(tx.WHY.format(text=escape(why(card.reason_codes, card.reason_text, card))))
    if card.recommendation:
        lines.append(tx.RECOMMENDATION.format(text=escape(card.recommendation)))
    if card.last_lead_message:
        last = card.last_lead_message.strip().replace("\n", " ")[:LAST_MAX]
        lines.append(tx.LAST_MESSAGE.format(text=escape(last)))
    if not card.crm_url.startswith("https://"):
        # Кнопка-ссылка в Telegram принимает только https; иначе — ссылка в тексте.
        lines.append(tx.CRM_OPEN.format(url=escape(card.crm_url, quote=True)))
    lines.append(_status_line(card))
    return "\n".join(line for line in lines if line)


def why(codes: Sequence[str], text: str | None, card: CardData | None = None) -> str:
    streak = card.kb_gap_streak if card is not None else 2
    result = "; ".join(tx.reason(code, streak) for code in codes if code in tx.REASONS)
    if text:
        result = f"{result}; {text}" if result else text
    return result


def products(keys: Sequence[str], names: Mapping[str, str] | None) -> list[str]:
    """Ключи интереса → названия; неизвестные ключи и служебный `company` отбрасываются."""
    if names is None:
        return [k for k in keys if k != "company"]
    return [names[k] for k in keys if k in names and k != "company"]


def duration(delta: timedelta) -> str:
    """«12 мин», «2 ч 5 мин», «2 д 3 ч»."""
    minutes = max(0, int(delta.total_seconds() // 60))
    if minutes < 60:
        return tx.MINUTES.format(n=minutes)
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return tx.HOURS.format(h=hours, m=minutes)
    days, hours = divmod(hours, 24)
    return tx.DAYS.format(d=days, h=hours)


def moment(at: datetime, now: datetime, timezone: str) -> str:
    """Время события по часовому поясу: сегодня — «14:20», в пределах недели — «пн 14:20»,
    раньше — «12.10 14:20»."""
    zone = ZoneInfo(timezone)
    local, today = at.astimezone(zone), now.astimezone(zone)
    if local.date() == today.date():
        return f"{local:%H:%M}"
    if today.date() - local.date() < timedelta(days=7):
        return f"{tx.WEEKDAYS[local.weekday()]} {local:%H:%M}"
    return f"{local:%d.%m %H:%M}"


def waiting(created_at: datetime, now: datetime, timezone: str) -> str:
    return tx.WAITING.format(
        waited=duration(now - created_at), since=moment(created_at, now, timezone)
    )


def _details(card: CardData) -> list[str]:
    details = []
    names = products(card.product_interest, card.product_names)
    if names:
        details.append(tx.INTEREST.format(text=escape(", ".join(names))))
    if card.timeline:
        timeline = tx.TIMELINES.get(card.timeline)
        if timeline:
            details.append(tx.TIMELINE.format(text=escape(timeline)))
    if card.decision_role:
        role = tx.ROLES.get(card.decision_role)
        if role:
            details.append(tx.ROLE.format(text=escape(role)))
    return details


def _status_line(card: CardData) -> str:
    now = card.now or datetime.now(ZoneInfo(card.timezone))
    if card.status == "taken" and card.taken_by:
        at = moment(card.taken_at, now, card.timezone) if card.taken_at else ""
        return tx.TAKEN_BY.format(name=escape(card.taken_by), at=at)
    if card.status == "snoozed":
        if card.snoozed_until is None:
            return tx.SNOOZED
        line = tx.SNOOZED_UNTIL.format(until=moment(card.snoozed_until, now, card.timezone))
        return line + (
            tx.SNOOZED_BY.format(name=escape(card.snoozed_by)) if card.snoozed_by else ""
        )
    if card.status in ("returned", "closed"):
        return tx.CLOSED if card.status == "closed" else tx.RETURNED
    wait = waiting(card.created_at, now, card.timezone) if card.created_at else ""
    overdue = tx.SLA_OVERDUE if card.sla_overdue else ""
    return "\n".join(part for part in (wait, overdue) if part)


def can_take(card: CardData) -> bool:
    return card.status in ("open", "snoozed")


def take_data(escalation_id: int) -> str:
    return f"{TAKE_PREFIX}{TAKE_ESCALATION}{escalation_id}"


def parse_take(data: str) -> tuple[str, int] | None:
    """`take:e15` → ("escalation", 15); старое `take:7` → ("lead", 7); мусор → None."""
    raw = data.removeprefix(TAKE_PREFIX)
    if raw.startswith(TAKE_ESCALATION) and raw[1:].isdigit():
        return "escalation", int(raw[1:])
    if raw.isdigit():
        return "lead", int(raw)
    return None


def is_silent(reason_codes: Sequence[str]) -> bool:
    """Передача только из «тихих» причин — без карточки в канале (сейчас таких причин нет)."""
    return bool(reason_codes) and set(reason_codes) <= SILENT_REASONS


def needs_sla(priority: str) -> bool:
    return priority in SLA_PRIORITIES

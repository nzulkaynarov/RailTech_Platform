"""Личные уведомления сотрудникам от бота (Q-010, аудит 2026-10-12 §3 п. 8).

Чистые правила: кому из сотрудников писать, когда можно снова написать менеджеру
о сообщении лида и текст уведомления. Отправку делает `services/staff_notifier.py`.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from html import escape
from typing import Final

PREVIEW_CHARS: Final = 120


@dataclass(frozen=True, slots=True)
class Staff:
    """Сотрудник глазами рассылки: роли, подписки и привязанный Telegram."""

    user_id: int
    roles: tuple[str, ...]
    is_active: bool
    tg_user_id: int | None
    notify_system: bool
    notify_leads: bool


def alert_recipients(staff: Iterable[Staff]) -> list[int]:
    """Telegram-id активных админов, подписанных на системные алерты; без дублей, по порядку."""
    seen: list[int] = []
    for s in staff:
        if (
            s.is_active
            and "admin" in s.roles
            and s.notify_system
            and s.tg_user_id is not None
            and s.tg_user_id not in seen
        ):
            seen.append(s.tg_user_id)
    return seen


def new_lead_recipients(staff: Iterable[Staff]) -> list[int]:
    """Telegram-id менеджеров и админов, подписанных на уведомления о лидах (D1-9): кому писать о
    запросе без
    ответственного. Без дублей, по порядку; неактивные и без привязанного Telegram пропускаются."""
    seen: list[int] = []
    for s in staff:
        if (
            s.is_active
            and ("manager" in s.roles or "admin" in s.roles)
            and s.notify_leads
            and s.tg_user_id is not None
            and s.tg_user_id not in seen
        ):
            seen.append(s.tg_user_id)
    return seen


def lead_dm_target(owner_mode: str, manager: Staff | None) -> int | None:
    """Кому писать о новом сообщении лида: ответственному менеджеру лида в работе у человека."""
    if owner_mode != "human" or manager is None:
        return None
    if not (manager.is_active and manager.notify_leads):
        return None
    return manager.tg_user_id


def lead_dm_due(last_sent_at: datetime | None, now: datetime, window: timedelta) -> bool:
    """Не чаще одного уведомления по лиду за окно."""
    return last_sent_at is None or now - last_sent_at >= window


def lead_dm_text(lead_name: str, text: str, lead_url: str, lead_id: int) -> str:
    """HTML: превью экранировано, ссылка — `<a href>` (сырой адрес не показывается).

    `lead_url` — готовый адрес лида (Платформа или старая CRM, `LinkBase.lead`)."""
    preview = " ".join(text.split())
    if len(preview) > PREVIEW_CHARS:
        preview = preview[: PREVIEW_CHARS - 1].rstrip() + "…"
    name = escape(lead_name.strip())
    who = f"лида #{lead_id} {name}" if name else f"лида #{lead_id}"
    body = f"«{escape(preview)}»" if preview else "(вложение)"
    link = escape(lead_url, quote=True)
    return f'💬 Новое сообщение от {who}: {body} — <a href="{link}">открыть</a>'


def web_lead_dm_text(
    template: str,
    *,
    name: str,
    company: str | None,
    need: str | None,
    minutes: int,
    lead_url: str,
    lead_id: int,
) -> str:
    """HTML-текст о запросе с сайта (`NEW_WEB_LEAD_DM`/`WEB_LEAD_OVERDUE_DM`): всё из формы
    экранировано."""
    preview = " ".join((need or "").split())
    if len(preview) > PREVIEW_CHARS:
        preview = preview[: PREVIEW_CHARS - 1].rstrip() + "…"
    who = escape(name.strip()) or f"#{lead_id}"
    if company and company.strip():
        who += f" ({escape(company.strip())})"
    link = escape(lead_url, quote=True)
    return template.format(
        lead_id=lead_id,
        who=who,
        need=f"«{escape(preview)}»" if preview else "без описания",
        minutes=minutes,
        link=f'<a href="{link}">открыть</a>',
    )

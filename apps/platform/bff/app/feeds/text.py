"""Тексты и время для строк Dashboard: «вчера», «3 ч назад», суммы, сроки по календарю компании.

Язык ответов BFF пока русский, как у ошибок (`app/errors.py`); перевод на uz и en — хвост фазы P2.
"""

from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

from app import session
from app.feeds.models import DueLabel

# Часовой пояс компании (03-frontend.md §8): Asia/Tashkent — UTC+5 без перехода на летнее время с
# 2005 года.
COMPANY_TZ = timezone(timedelta(hours=5))
NBSP = " "


def now_utc() -> datetime:
    """Текущее время; идёт через `app.session.now`, чтобы тесты управляли им одними часами со всей
    сессией."""
    return datetime.fromtimestamp(session.now(), UTC)


def parse_dt(value: Any) -> datetime | None:
    """ISO-время бэкенда -> aware UTC; пусто и мусор — None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def parse_deadline(value: Any) -> datetime | None:
    """Срок: дата без времени (`2026-10-28`) истекает в конце этого дня по календарю компании."""
    if isinstance(value, str) and len(value) == 10:
        parsed = parse_dt(f"{value}T23:59:59+05:00")
        return parsed
    return parse_dt(value)


def company_day(moment: datetime) -> int:
    """Порядковый номер календарного дня компании (для сравнения «сегодня» и «завтра»)."""
    return moment.astimezone(COMPANY_TZ).date().toordinal()


def due_label(due_at: datetime | None, now: datetime, *, default: DueLabel = "later") -> DueLabel:
    """Бейдж срока: до сейчас — просрочено, тот же день компании — сегодня, следующий — завтра."""
    if due_at is None:
        return default
    if due_at < now:
        return "overdue"
    days = company_day(due_at) - company_day(now)
    if days <= 0:
        return "today"
    return "tomorrow" if days == 1 else "later"


def ago(then: datetime | None, now: datetime) -> str:
    """«только что», «15 мин назад», «3 ч назад», «вчера», «5 дн. назад»."""
    if then is None:
        return ""
    seconds = (now - then).total_seconds()
    if seconds < 60:
        return "только что"
    if seconds < 3600:
        return f"{int(seconds // 60)} мин назад"
    if seconds < 86400:
        return f"{int(seconds // 3600)} ч назад"
    days = company_day(now) - company_day(then)
    if days <= 1:
        return "вчера"
    return f"{days} дн. назад"


def money(amount: Any, currency: str | None) -> str | None:
    """`1 234 567 сум`; другая валюта — её код. Нечисло — None."""
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, ValueError):
        return None
    shown = f"{value:,.2f}" if value != value.to_integral_value() else f"{int(value):,}"
    shown = shown.replace(",", NBSP).replace(".", ",")
    code = (currency or "UZS").upper()
    return f"{shown}{NBSP}{'сум' if code == 'UZS' else code}"


def short(text: Any, limit: int = 90) -> str:
    """Одна строка не длиннее `limit` символов."""
    if not isinstance(text, str):
        return ""
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def join(*parts: str | None) -> str:
    """Подпись «клиент · объект · когда»: пустые части отбрасываются."""
    return " · ".join(p for p in parts if p)


def segment(value: str) -> str:
    """Бизнес-номер в пути SPA: `КП-2026/118` -> `%D0%9A…2F118` (03-frontend.md §6)."""
    return quote(value, safe="")

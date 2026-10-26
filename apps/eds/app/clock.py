"""Время сервиса: единая точка «сейчас» и часовой пояс компании.

Год номера реестра и даты фильтров считаются по `Asia/Tashkent` (runbook волны 12 §2.1). Тесты подменяют `now`.
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

COMPANY_TZ = ZoneInfo("Asia/Tashkent")


def now() -> datetime:
    """Текущий момент, UTC."""
    return datetime.now(UTC)


def company_date(moment: datetime) -> date:
    """Календарная дата момента по часовому поясу компании."""
    return moment.astimezone(COMPANY_TZ).date()


def company_year(moment: datetime) -> int:
    return company_date(moment).year

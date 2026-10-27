"""Инциденты, оповещения и сводка внешних сервисов (M3-CRM-12, ADR-0024). Чистые функции.

Инцидент открывает переход в `fail`, закрывает `ok`/`warn`; `unknown`/`off` (нет данных, не
подключён) инцидент не меняют. Инцидент — журнал «с … по …» по сервису; оповещения о причинах
(одно «сломано» после 15 минут и одно «восстановлено») — в `external_cause`.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from app.domain.external_registry import Status
from app.domain.system_status import Component

Transition = Literal["open", "update", "close", "none"]
SUMMARY_KEY: Final = "external_services"
SUMMARY_TITLE: Final = "Внешние сервисы"


@dataclass(frozen=True, slots=True)
class OpenIncident:
    id: int
    started_at: datetime
    alerted_at: datetime | None


def transition(open_incident: OpenIncident | None, status: Status) -> Transition:
    if status == "fail":
        return "update" if open_incident is not None else "open"
    if status in ("ok", "warn") and open_incident is not None:
        return "close"
    return "none"


def duration_text(delta: timedelta) -> str:
    """«меньше минуты», «12 мин», «2 ч 5 мин», «3 дн 4 ч»."""
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        return "меньше минуты"
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days} дн {hours} ч" if hours else f"{days} дн"
    if hours:
        return f"{hours} ч {mins} мин" if mins else f"{hours} ч"
    return f"{mins} мин"


@dataclass(frozen=True, slots=True)
class AlertText:
    subject: str
    lines: tuple[str, ...]

    @property
    def plain(self) -> str:
        return "\n".join((self.subject, *self.lines))


@dataclass(frozen=True, slots=True)
class Counts:
    ok: int = 0
    warn: int = 0
    fail: int = 0
    unknown: int = 0
    off: int = 0
    disabled: int = 0


def count(rows: Iterable[tuple[Status, bool]]) -> Counts:
    """`rows` — (статус, выключен вручную) по каждому сервису реестра."""
    tally: dict[str, int] = {}
    disabled = 0
    for status, off in rows:
        tally[status] = tally.get(status, 0) + 1
        disabled += int(off)
    return Counts(
        ok=tally.get("ok", 0),
        warn=tally.get("warn", 0),
        fail=tally.get("fail", 0),
        unknown=tally.get("unknown", 0),
        off=tally.get("off", 0),
        disabled=disabled,
    )


def uptime(by_status: Mapping[str, int]) -> float | None:
    """Доля исправных проверок (ok + warn) среди проверок с ответом; без таких — None."""
    up = by_status.get("ok", 0) + by_status.get("warn", 0)
    total = up + by_status.get("fail", 0)
    return round(up / total, 4) if total else None


def summary_component(
    counts: Counts, failing: Iterable[str], warning: Iterable[str], now: datetime, *, checked: bool
) -> Component:
    """Строка-сводка на «Состоянии системы»; подробности — на странице «Внешние сервисы»."""
    if not checked:
        reason = "Проверок ещё не было — фоновая проверка раз в минуту"
        return Component(SUMMARY_KEY, SUMMARY_TITLE, "unknown", reason, now)
    fails, warns = list(failing), list(warning)
    manual = f", выключено вручную {counts.disabled}" if counts.disabled else ""
    tail = f"; в норме {counts.ok}{manual}"
    if fails:
        return Component(SUMMARY_KEY, SUMMARY_TITLE, "fail", f"Сбой: {', '.join(fails)}{tail}", now)
    if warns:
        reason = f"Внимание: {', '.join(warns)}{tail}"
        return Component(SUMMARY_KEY, SUMMARY_TITLE, "warn", reason, now)
    return Component(SUMMARY_KEY, SUMMARY_TITLE, "ok", f"В норме: {counts.ok}{manual}", now)

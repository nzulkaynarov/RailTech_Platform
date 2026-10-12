"""Экран «Состояние системы» (аудит 2026-10-12 §3 п. 6): факты → статус и понятная причина.

Чистые функции: сервис собирает факты (готовность зависимостей, строки `system_alerts`,
очередь, конфигурация), здесь — только правила «ok / warn / fail / unknown» и тексты.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal

from app.domain.alerts import QUEUE_LIMIT

Status = Literal["ok", "warn", "fail", "unknown"]
STALLED_MINUTES: Final = 15

_DEPENDENCIES: Final = {
    "database": ("База данных", "PostgreSQL недоступен — CRM и бот не работают"),
    "s3": ("Хранилище файлов", "S3 (RustFS) недоступно — документы и вложения не сохраняются"),
    "litellm": ("Шлюз моделей", "LiteLLM недоступен — бот не отвечает клиентам"),
}


@dataclass(frozen=True, slots=True)
class Component:
    key: str
    title: str
    status: Status
    reason: str
    checked_at: datetime | None


@dataclass(frozen=True, slots=True)
class AlertRow:
    """Строка `system_alerts`, как её оставил монитор."""

    key: str
    active: bool
    detail: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QueueFacts:
    waiting: int
    stalled: int
    failed_last_hour: int


def dependencies(checks: Mapping[str, bool], now: datetime) -> list[Component]:
    result = []
    for key, (title, problem) in _DEPENDENCIES.items():
        if key not in checks:
            continue
        ok = checks[key]
        result.append(Component(key, title, "ok" if ok else "fail", "" if ok else problem, now))
    return result


def models(alerts: Sequence[AlertRow]) -> list[Component]:
    """Модели — по последней проверке монитора (раз в час); сами здесь не вызываются."""
    rows = sorted((a for a in alerts if a.key.startswith("model:")), key=lambda a: a.key)
    if not rows:
        return [
            Component(
                "models",
                "Модели ИИ",
                "unknown",
                "Монитор ещё не проверял модели — проверка раз в час, в начале часа",
                None,
            )
        ]
    return [
        Component(
            a.key,
            f"Модель {a.key.split(':', 1)[1]}",
            "fail" if a.active else "ok",
            (a.detail or "проблема у провайдера") if a.active else "",
            a.updated_at,
        )
        for a in rows
    ]


def budget(alerts: Sequence[AlertRow], now: datetime) -> Component:
    row = next((a for a in alerts if a.key == "budget"), None)
    if row is not None and row.active:
        return Component("budget", "Бюджет моделей", "warn", row.detail or "", row.updated_at)
    return Component("budget", "Бюджет моделей", "ok", "", row.updated_at if row else now)


def bot(running: bool | None, mode: str, now: datetime) -> Component:
    if running is None:
        return Component(
            "bot",
            "Telegram-бот",
            "fail",
            "Бот выключен: нет токена или TELEGRAM_MODE=disabled",
            now,
        )
    if not running:
        return Component("bot", "Telegram-бот", "fail", "Бот остановился — перезапустите api", now)
    return Component("bot", "Telegram-бот", "ok", f"режим {mode}", now)


def channel(channel_id: int | None, now: datetime) -> Component:
    if channel_id is None:
        return Component(
            "channel",
            "Канал команды",
            "warn",
            "Канал не указан в «Настройках» — передачи менеджерам никуда не приходят",
            now,
        )
    return Component("channel", "Канал команды", "ok", "", now)


def queue(facts: QueueFacts, now: datetime) -> Component:
    problems = []
    if facts.stalled:
        problems.append(f"{facts.stalled} задач выполняются дольше {STALLED_MINUTES} минут")
    if facts.waiting > QUEUE_LIMIT:
        problems.append(f"{facts.waiting} задач в ожидании (порог {QUEUE_LIMIT})")
    if facts.failed_last_hour:
        problems.append(f"{facts.failed_last_hour} задач упали за последний час")
    status: Status = "warn" if problems else "ok"
    reason = "; ".join(problems) if problems else f"в ожидании: {facts.waiting}"
    return Component("queue", "Очередь задач", status, reason, now)


def backup(now: datetime) -> Component:
    return Component(
        "backup",
        "Последний бэкап",
        "unknown",
        "Бэкапы лежат в томе сервера, CRM их не видит — проверьте по runbook backup-restore",
        now,
    )


def secrets(missing: Sequence[str], now: datetime) -> Component:
    if missing:
        names = ", ".join(missing)
        return Component("secrets", "Секреты сервера", "fail", f"Не заданы в .env: {names}", now)
    return Component("secrets", "Секреты сервера", "ok", "все обязательные заданы", now)

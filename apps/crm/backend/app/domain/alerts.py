"""Системные алерты в канал команды (SPEC §13): правила и дедупликация.

Чистые функции: снимок здоровья → активные проверки → решение по каждой
(отправить / напомнить / снять / ничего). Состояние хранит `system_alerts`.
"""

from collections.abc import Callable, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

# Прежние алерты ушли в центр внешних сервисов (W15-H3b): монитор их больше не шлёт, а живые строки
# `system_alerts` закрывает молча. «Шлюз моделей недоступен» (`litellm`) и сбои ответов ИИ
# (`vendor.*`, `litellm`) идут по общей политике причин: 15 минут подряд, 5 минут `ok`, раз в сутки.
RETIRED_KEYS: Final = frozenset({"litellm_down", "ai_failures"})
# Пороги монитора — одно место (технические, не бизнес-правила: в «Настройки» не выносим).
QUEUE_LIMIT: Final = 100
BUDGET_WARN_SHARE: Final = 0.8
REPEAT_AFTER: Final = timedelta(hours=6)
MODEL_PROBE_MINUTE: Final = 0  # раз в час: каждая проба — платный запрос
_BILLING: Final = (
    "credit balance",
    "insufficient",
    "quota",
    "billing",
    "payment",
    "exceeded your current",
)
_AUTH: Final = ("api key", "api_key", "x-api-key", "authentication", "unauthorized", "permission")


@dataclass(frozen=True)
class HealthSnapshot:
    """Что видит монитор раз в минуту."""

    failed_tasks: dict[str, int] = field(default_factory=dict)  # задача → упавших за окно
    queue_size: int = 0
    litellm_ok: bool = True
    spent_usd: float = 0.0
    daily_budget_usd: float = 0.0  # 0 — без лимита
    # Проверка моделей у провайдеров: алиас → проблема или None; None целиком — не проверяли.
    models: dict[str, str | None] | None = None
    # Задачи, у которых после последнего сбоя был успешный запуск: только они «в норме».
    recovered_tasks: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Check:
    key: str
    active: bool
    title: str
    detail: str
    grace: timedelta = timedelta(0)
    hint: str = ""  # «что делать» — для задач воркера и сбоев ИИ


@dataclass(frozen=True)
class AlertState:
    """Строка `system_alerts`: с какого момента наблюдается и когда отправляли."""

    first_seen_at: datetime | None
    sent_at: datetime | None


class Decision(StrEnum):
    NONE = "none"
    FIRE = "fire"
    REPEAT = "repeat"
    RESOLVE = "resolve"


TaskTexts = Callable[[str], tuple[str, str]]


def _task_texts(task: str) -> tuple[str, str]:
    return f"Задача {task}", ""


def checks(
    snapshot: HealthSnapshot,
    known_failed: Set[str] = frozenset(),
    task_texts: TaskTexts = _task_texts,
) -> list[Check]:
    """Проверки SPEC §13; `known_failed` — задачи, по которым алерт уже есть (чтобы снять).

    Алерт задачи снимается только успешным запуском после сбоя (`recovered_tasks`),
    а не тем, что сбой ушёл из часового окна."""
    result = [
        Check(
            "queue_size",
            snapshot.queue_size > QUEUE_LIMIT,
            "Очередь задач",
            f"{snapshot.queue_size} задач в ожидании (порог {QUEUE_LIMIT})",
        )
    ]
    budget = snapshot.daily_budget_usd
    share = snapshot.spent_usd / budget if budget > 0 else 0.0
    result.append(
        Check(
            "budget",
            share > BUDGET_WARN_SHARE,
            "Бюджет моделей",
            f"${snapshot.spent_usd:.2f} из ${budget:.2f} за сегодня ({share:.0%})",
        )
    )
    for alias, problem in sorted((snapshot.models or {}).items()):
        result.append(
            Check(f"model:{alias}", problem is not None, f"Модель {alias}", problem or "")
        )
    for task in sorted(set(snapshot.failed_tasks) | set(known_failed)):
        count = snapshot.failed_tasks.get(task, 0)
        title, hint = task_texts(task)
        detail = (
            f"упала после всех попыток: {count} за последний час"
            if count
            else "упала после всех попыток; успешного запуска после сбоя ещё не было"
        )
        result.append(
            Check(
                f"failed_task:{task}",
                task not in snapshot.recovered_tasks,
                title,
                detail,
                hint=hint,
            )
        )
    return result


def decide(
    check: Check, state: AlertState | None, now: datetime, repeat_after: timedelta = REPEAT_AFTER
) -> Decision:
    """Отправка только на переходах; активный алерт напоминается не чаще `repeat_after`."""
    if not check.active:
        return (
            Decision.RESOLVE if state is not None and state.sent_at is not None else Decision.NONE
        )
    since = state.first_seen_at if state is not None and state.first_seen_at else now
    if now - since < check.grace:
        return Decision.NONE
    if state is None or state.sent_at is None:
        return Decision.FIRE
    return Decision.REPEAT if now - state.sent_at >= repeat_after else Decision.NONE


def message(check: Check, decision: Decision) -> str:
    if decision is Decision.RESOLVE:
        return f"✅ {check.title}: в норме"
    suffix = "" if decision is Decision.FIRE else " (всё ещё)"
    return f"⚠️ {check.title}: {check.detail}{suffix}"


def model_probe_due(now: datetime) -> bool:
    """Модели проверяются запросом раз в час (монитор работает каждую минуту)."""
    return now.minute == MODEL_PROBE_MINUTE


def provider_problem(status: int | None, text: str) -> str | None:
    """Ответ провайдера, о котором должна знать команда: кредиты/квота или отклонённый ключ.

    Временные сбои (перегрузка 529, таймаут) — не здесь: их покрывают ретраи и строки «Шлюз моделей»
    и провайдеров центра внешних сервисов.
    """
    lowered = text.lower()
    if any(word in lowered for word in _BILLING):
        return "закончились кредиты или квота у провайдера — пополните баланс; бот не отвечает"
    if status in (401, 403) or any(word in lowered for word in _AUTH):
        return "провайдер отклонил ключ — проверьте ключ API; бот не отвечает"
    return None

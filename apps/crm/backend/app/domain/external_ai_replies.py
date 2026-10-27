"""Строка «Ответы ИИ клиентам» центра внешних сервисов (W15-H3b, ADR-0024).

Источник — ответы бота за последние минуты (`messages`, `role = bot`): ответ агента несёт
`meta.action`, сбой агента (модель, crm-mcp, LangGraph) — `meta.error = agent_unavailable`.
Прежний алерт монитора `ai_failures` («Сбой сразу» по первой передаче) снят: сигнал идёт по общей
политике причин — «Сломано» только при непрерывном сбое от 15 минут, «Восстановлено» после 5 минут
без сбоев при живом трафике, не больше одного письма в сутки, «Нестабильно» без писем. Клиента при
сбое менеджеру передаёт сам бот: карточка в канал команды — рабочая задача менеджера, не системный
алерт.

Состояние держится по последнему ответу бота за сутки, а не по окну: ночью обращений нет, но
последний ответ успешный — строка `ok` (иначе «Восстановлено» не пришло бы). `unknown` — только
если за сутки ответов не было совсем или последнее событие — давний сбой без ответов после него
(данных нет: это не сбой и не восстановление).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from app.domain.external_status import CheckResult

KEY: Final = "ai_replies"
#: Окно ответов бота, мин: сбой «живёт» в нём, пока после него не было успешного ответа.
WINDOW_MINUTES: Final = 5


@dataclass(frozen=True, slots=True)
class AiFacts:
    failed: int = 0  # ответов «сбой ИИ» за окно
    answered: int = 0  # успешных ответов агента за окно
    last_failed_at: datetime | None = None  # последний сбой за сутки
    last_answered_at: datetime | None = None  # последний успешный ответ за сутки


def ai_replies(f: AiFacts, now: datetime) -> CheckResult:
    metrics = {"failed_5m": f.failed, "answered_5m": f.answered}
    last_is_failure = f.last_failed_at is not None and (
        f.last_answered_at is None or f.last_answered_at < f.last_failed_at
    )
    if last_is_failure and f.last_failed_at is not None:
        if now - f.last_failed_at <= timedelta(minutes=WINDOW_MINUTES):
            return CheckResult(
                KEY,
                "fail",
                f"ИИ не ответил клиентам за {WINDOW_MINUTES} мин: {max(f.failed, 1)}; "
                "их передают менеджерам",
                hint=(
                    "Проверьте строки «Шлюз моделей» и провайдеров в «Подключениях»; клиентов из "
                    "этого сбоя ведёт менеджер по карточке в канале команды"
                ),
                metrics=metrics,
                cause="ai_unavailable",
            )
        return _unknown("После сбоя ответов не было — нечего проверять", metrics)
    if f.last_answered_at is not None:
        return CheckResult(KEY, "ok", "ИИ отвечает клиентам", metrics=metrics)
    return _unknown("Ответов бота за сутки не было — нечего проверять", metrics)


def _unknown(summary: str, metrics: dict[str, int]) -> CheckResult:
    return CheckResult(KEY, "unknown", summary, metrics=metrics)

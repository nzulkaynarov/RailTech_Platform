"""Строка «Ответы ИИ клиентам» центра внешних сервисов (W15-H3b, ADR-0024).

Источник — ответы бота за последние минуты (`messages`, `role = bot`): ответ агента несёт
`meta.action`, сбой агента (модель, crm-mcp, LangGraph) — `meta.error = agent_unavailable`.
Прежний алерт монитора `ai_failures` («Сбой сразу» по первой передаче) снят: сигнал идёт по общей
политике причин — «Сломано» только при непрерывном сбое от 15 минут, «Восстановлено» после 5 минут
без сбоев при живом трафике, не больше одного письма в сутки, «Нестабильно» без писем. Клиента при
сбое менеджеру передаёт сам бот: карточка в канал команды — рабочая задача менеджера, не системный
алерт.

Нет обращений за окно — `unknown`: это не сбой и не восстановление.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.domain.external_status import CheckResult

KEY: Final = "ai_replies"
#: Окно ответов бота, мин: сбой «живёт» в нём, пока после него не было успешного ответа.
WINDOW_MINUTES: Final = 5


@dataclass(frozen=True, slots=True)
class AiFacts:
    failed: int = 0  # ответов «сбой ИИ» за окно
    answered: int = 0  # успешных ответов агента за окно
    last_failed_at: datetime | None = None
    last_answered_at: datetime | None = None


def ai_replies(f: AiFacts) -> CheckResult:
    metrics = {"failed_5m": f.failed, "answered_5m": f.answered}
    if f.failed == 0 and f.answered == 0:
        return CheckResult(
            KEY,
            "unknown",
            f"Обращений за последние {WINDOW_MINUTES} мин не было — нечего проверять",
            metrics=metrics,
        )
    recovered = f.last_answered_at is not None and (
        f.last_failed_at is None or f.last_answered_at > f.last_failed_at
    )
    if f.failed and not recovered:
        return CheckResult(
            KEY,
            "fail",
            f"ИИ не ответил клиентам за {WINDOW_MINUTES} мин: {f.failed}; их передают менеджерам",
            hint=(
                "Проверьте строки «Шлюз моделей» и провайдеров в «Подключениях»; клиентов из этого "
                "сбоя ведёт менеджер по карточке в канале команды"
            ),
            metrics=metrics,
            cause="ai_unavailable",
        )
    return CheckResult(KEY, "ok", "ИИ отвечает клиентам", metrics=metrics)

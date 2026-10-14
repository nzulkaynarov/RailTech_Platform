"""Граница ИИ-задачи: контекст трейса, бюджет как код результата, итог в журнале.

`run_ai_job` (очередь `ai`) вызывает обработчик функции внутри `run_traced_job`: все вызовы
шлюза получают `session_id` = id задачи и сотрудника-владельца (из `AIJob`, не из payload),
а исчерпанный бюджет превращается в результат `{"error": "AI_BUDGET_EXCEEDED"}` — фронтенд
показывает его через общий словарь `apiErrors.*`, как остальные коды задач.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from .context import trace_scope
from .errors import AI_BUDGET_EXCEEDED, AIBudgetExceeded

logger = logging.getLogger(__name__)


def _owner_id(job_id: str) -> int | None:
    from ai.models import AIJob

    return AIJob.objects.filter(celery_task_id=job_id).values_list("owner_id", flat=True).first()


def run_traced_job(job_id: str, feature: str, handler: Callable[[dict], dict], payload: dict) -> dict:
    """Выполнить обработчик задачи в контексте трейса; бюджет → стабильный код ошибки."""
    with trace_scope(job_id, user_id=_owner_id(job_id), job_feature=feature) as trace:
        try:
            result = handler(payload)
        except AIBudgetExceeded as exc:
            logger.warning("AI job %s (%s) stopped: %s", job_id, feature, exc)
            return {"error": AI_BUDGET_EXCEEDED}
        if trace.calls:
            logger.info(
                "AI job %s (%s): calls=%s in=%s out=%s cost=%s prompts=%s",
                job_id,
                feature,
                trace.calls,
                trace.input_tokens,
                trace.output_tokens,
                trace.cost_usd,
                trace.prompt_versions,
            )
        return result

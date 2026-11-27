"""Политика задач очереди (ЗАВИС-1): что делать с задачей, оставшейся в `doing`, и сколько ей идти.

Каждая задача очереди обязана быть здесь явно (тест сверяет с `queue.tasks`): молчаливого «по
умолчанию» нет, потому что повтор неидемпотентной задачи (письмо, сообщение клиенту) — вред.

- `periodic` — следующий тик всё равно запустит работу: зависшую помечаем упавшей;
- `idempotent` — повтор безопасен (идемпотентные ключи, дедупликация, повторяемая индексация):
  зависшую ставим в очередь заново;
- `once` — повтор опасен (двойная отправка, платный вызов): помечаем упавшей и пишем в журнал.

`timeout_s` — предельное время выполнения: по истечении задача отменяется и становится `failed`,
а не висит в `doing` вечно (зависший вызов без таймаута при живом воркере иначе не снять).
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

import structlog

logger = structlog.get_logger(__name__)


class Kind(StrEnum):
    PERIODIC = "periodic"
    IDEMPOTENT = "idempotent"
    ONCE = "once"


@dataclass(frozen=True, slots=True)
class JobPolicy:
    kind: Kind
    timeout_s: float = 600.0


def _periodic(timeout_s: float = 300.0) -> JobPolicy:
    return JobPolicy(Kind.PERIODIC, timeout_s)


def _idem(timeout_s: float = 600.0) -> JobPolicy:
    return JobPolicy(Kind.IDEMPOTENT, timeout_s)


def _once(timeout_s: float = 600.0) -> JobPolicy:
    return JobPolicy(Kind.ONCE, timeout_s)


POLICIES: Final[dict[str, JobPolicy]] = {
    # периодические: тик через минуту-две запускает то же самое
    "builtin:procrastinate.builtin_tasks.remove_old_jobs": _idem(),
    "procrastinate.builtin_tasks.remove_old_jobs": _idem(),
    "daily_report": _periodic(),
    "email_queue_sweep": _periodic(),
    "erp_notices_sweep": _periodic(),
    "escalation_digest": _periodic(),
    "external_checks_cheap": _periodic(240),
    "external_checks_heavy": _periodic(480),
    "external_checks_recheck": _periodic(480),
    "inbound_mail_poll": _periodic(300),
    "mark_unresponsive": _periodic(),
    "refresh_dashboard": _periodic(),
    "rt_bus.log_metrics": _periodic(),
    "rt_bus.pump": _periodic(),
    "rt_bus.purge": _periodic(),
    "rt_bus.requeue_stuck_inbox": _periodic(),
    "rt_bus_jobs_cleanup": _periodic(),
    "snooze_expiry": _periodic(),
    "staff_chat_reconcile": _periodic(),
    "system_monitor": _periodic(),
    "web_lead_sla_sweep": _periodic(),
    "stalled_jobs_recovery": _periodic(120),
    # повтор безопасен: идемпотентные ключи ERP, дедупликация шины, переиндексация
    "erp_create_request": _idem(),
    "erp_handoff_client": _idem(),
    "erp_provision_user": _idem(),
    "erp_revoke_sessions": _idem(),
    "staff_chat_removal": _idem(),
    "extract_document_text": _idem(1800),
    "ingest_kb_document": _idem(1800),
    "rt_bus.process_inbox": _idem(),
    # загрузка писем за период идемпотентна (дубль ловит UNIQUE message_id)
    "inbound_mail_history": _idem(1800),
    # повтор опасен: сообщения людям, письма, платные вызовы моделей, пользовательская загрузка
    "send_email": _once(),
    "deliver_client_notice": _once(),
    "escalation_reminder": _once(),
    "escalation_sla_check": _once(),
    "lead_handed_over": _once(),
    "notify_lead_message": _once(),
    "notify_web_lead": _once(),
    "refresh_chat_menu": _once(),
    "sync_escalation_post": _once(),
    "web_lead_sla_check": _once(),
    "qualify_lead": _once(900),
}


def policy_of(task_name: str) -> JobPolicy | None:
    return POLICIES.get(task_name)


async def enforce_timeout(
    call_next: Callable[[], Awaitable[Any]], context: Any, worker: Any
) -> Any:
    """Воркер-мидлвар: задача дольше своего `timeout_s` отменяется и становится `failed`."""
    policy = policy_of(context.job.task_name)
    if policy is None:
        return await call_next()
    try:
        async with asyncio.timeout(policy.timeout_s):
            return await call_next()
    except TimeoutError:
        logger.error(
            "job_timeout",
            task=context.job.task_name,
            job_id=context.job.id,
            limit_s=policy.timeout_s,
        )
        raise

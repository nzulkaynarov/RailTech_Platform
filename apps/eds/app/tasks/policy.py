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
    "builtin:procrastinate.builtin_tasks.remove_old_jobs": _idem(),
    "procrastinate.builtin_tasks.remove_old_jobs": _idem(),
    # периодические: следующий тик запускает то же самое
    "sso_jti_cleanup": _periodic(),
    "idempotency_cleanup": _periodic(),
    "instruction_reminders": _periodic(),
    "signing_expiry_reminders": _periodic(),
    "render_sweep": _periodic(),
    "rt_bus.log_metrics": _periodic(),
    "rt_bus.pump": _periodic(),
    "rt_bus.purge": _periodic(),
    "rt_bus.requeue_stuck_inbox": _periodic(),
    "stalled_jobs_recovery": _periodic(120),
    # повтор безопасен: рендер по хешу пишет один и тот же файл, inbox шины дедуплицируется
    "render_pdf": _idem(900),
    "rt_bus.process_inbox": _idem(),
}


def policy_of(task_name: str) -> JobPolicy | None:
    return POLICIES.get(task_name)


async def enforce_timeout(call_next: Callable[[], Awaitable[Any]], context: Any, worker: Any) -> Any:
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

"""Повтор задач очереди к ERP: на 429 ждём `Retry-After`, не своё расписание (шов 0.3.0, FIX-60).

ERP ограничивает частоту запросов сервисного токена и отвечает 429 `TOO_MANY_REQUESTS` с паузой
в секундах (`ErpRateLimitedError.retry_after_s`). Обычное расписание (линейная пауза) могло бы
повторить раньше и снова упереться в лимит. Число попыток при этом общее с остальными временными
сбоями (`max_attempts`): бесконечно ждать лимит задача не будет, после последней попытки итог —
`failed`, как у любого сбоя.
"""

from procrastinate import RetryStrategy
from procrastinate.jobs import Job
from procrastinate.retry import RetryDecision

from app.domain.errors import ErpRateLimitedError


class ErpRetryStrategy(RetryStrategy):
    """`RetryStrategy`, у которого пауза после 429 — не короче `Retry-After` ответа ERP."""

    def get_retry_decision(self, *, exception: BaseException, job: Job) -> RetryDecision | None:
        decision = super().get_retry_decision(exception=exception, job=job)
        if decision is None or not isinstance(exception, ErpRateLimitedError):
            return decision
        scheduled = (
            self.wait
            + self.linear_wait * job.attempts
            + self.exponential_wait ** (job.attempts + 1)
        )
        return RetryDecision(retry_in={"seconds": max(scheduled, exception.retry_after_s)})


__all__ = ["ErpRetryStrategy"]

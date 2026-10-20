"""Задача `erp_handoff_client` (FIX-31): очередь, блокировки, повторы только для временных сбоев."""

import pytest
from procrastinate import testing

from app.tasks import erp_handoff
from app.tasks.queue import TASK_MODULES, queue


@pytest.mark.asyncio
async def test_enqueue_defers_the_task_under_per_client_locks() -> None:
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        job_id = await erp_handoff.enqueue_erp_handoff(5, 9, 3)

    (job,) = connector.jobs.values()
    assert job_id is not None
    assert job["task_name"] == "erp_handoff_client"
    assert job["args"] == {"client_id": 5, "lead_id": 9, "actor_user_id": 3}
    assert job["queue_name"] == "notify"
    assert job["lock"] == "erp_handoff:5"
    assert job["queueing_lock"] == "erp_handoff:5"


@pytest.mark.asyncio
async def test_double_click_does_not_queue_a_second_waiting_task() -> None:
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        first = await erp_handoff.enqueue_erp_handoff(5, 9, 3)
        second = await erp_handoff.enqueue_erp_handoff(5, 9, 3)
        other_client = await erp_handoff.enqueue_erp_handoff(6, 10, 3)

    assert first is not None
    assert second is None
    assert other_client is not None
    assert len(connector.jobs) == 2


def test_task_retries_with_growing_pause_and_is_registered() -> None:
    retry = erp_handoff.RETRY
    assert (retry.max_attempts or 0) >= 5
    assert (retry.linear_wait or 0) > 0
    assert queue.tasks["erp_handoff_client"].retry_strategy is retry
    assert "app.tasks.erp_handoff" in TASK_MODULES


class _Job:
    def __init__(self, attempts: int) -> None:
        self.attempts = attempts


class _Context:
    def __init__(self, attempts: int) -> None:
        self.job = _Job(attempts)


@pytest.mark.asyncio
async def test_last_attempt_is_the_one_procrastinate_will_not_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повтор идёт, пока `attempts < max_attempts`: `final_attempt` — ровно последний запуск."""
    seen: list[bool] = []

    class _Service:
        async def run(
            self, client_id: int, lead_id: int, actor: int | None, *, final_attempt: bool
        ) -> str:
            seen.append(final_attempt)
            return "done"

    class _Container:
        erp_handoff_service = _Service()

    monkeypatch.setattr(erp_handoff, "get_container", lambda: _Container())
    retry = erp_handoff.RETRY
    max_attempts = retry.max_attempts or 0
    retried: list[bool] = []
    for attempts in range(max_attempts + 2):
        await erp_handoff.erp_handoff_client(_Context(attempts), 5, 9, 3)  # type: ignore[arg-type]
        retried.append(retry.get_retry_exception(RuntimeError("x"), _Job(attempts)) is not None)  # type: ignore[arg-type]

    # `final_attempt` истинно ровно там, где Procrastinate больше не повторит
    assert seen == [not again for again in retried]
    assert seen.index(True) == max_attempts
    assert seen[:max_attempts] == [False] * max_attempts

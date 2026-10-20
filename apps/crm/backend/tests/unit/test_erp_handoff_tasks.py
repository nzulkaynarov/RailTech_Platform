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

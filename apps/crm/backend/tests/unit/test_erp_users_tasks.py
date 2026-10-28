"""Задачи `erp_provision_user` и `erp_revoke_sessions` (FIX-11): очередь, блокировка, повторы."""

import pytest
from procrastinate import testing

from app.tasks import erp_users
from app.tasks.queue import queue


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "task_name"),
    [("provision", "erp_provision_user"), ("revoke", "erp_revoke_sessions")],
)
async def test_enqueue_defers_the_right_task_under_a_per_user_lock(
    action: str, task_name: str
) -> None:
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        await erp_users.enqueue_erp_sync(action, 5)

    (job,) = connector.jobs.values()
    assert job["task_name"] == task_name
    assert job["args"] == {"user_id": 5}
    assert job["queue_name"] == "notify"
    assert job["lock"] == "erp_user:5"
    assert job["queueing_lock"] == f"erp_user_q:{action}:5"


@pytest.mark.asyncio
async def test_second_waiting_job_for_the_same_user_and_action_is_not_queued() -> None:
    """D2-1: массовый провижининг по отпечатку каталога не плодит дублей ждущих задач."""
    connector = testing.InMemoryConnector()
    with queue.replace_connector(connector):
        first = await erp_users.enqueue_erp_sync("provision", 5)
        second = await erp_users.enqueue_erp_sync("provision", 5)
        other = await erp_users.enqueue_erp_sync("revoke", 5)

    assert first is not None
    assert second is None
    assert other is not None
    assert len(connector.jobs) == 2


def test_tasks_retry_with_growing_pause() -> None:
    retry = erp_users.RETRY
    assert (retry.max_attempts or 0) >= 5
    assert (retry.linear_wait or 0) > 0
    for name in ("erp_provision_user", "erp_revoke_sessions"):
        assert queue.tasks[name].retry_strategy is retry


def test_task_module_is_registered_for_the_worker() -> None:
    from app.tasks.queue import TASK_MODULES

    assert "app.tasks.erp_users" in TASK_MODULES

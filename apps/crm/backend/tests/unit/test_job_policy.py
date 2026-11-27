"""Политика задач очереди (ЗАВИС-1): решение на каждую задачу."""

import asyncio
import importlib
from types import SimpleNamespace
from typing import Any

import pytest

from app.tasks import policy
from app.tasks.queue import TASK_MODULES, queue
from app.tasks.stalled import decide


def _load_tasks() -> set[str]:
    for module in TASK_MODULES:
        importlib.import_module(module)
    return set(queue.tasks)


def test_every_queue_task_has_an_explicit_policy() -> None:
    missing = _load_tasks() - set(policy.POLICIES)
    assert not missing, f"добавьте задачи в app/tasks/policy.py: {sorted(missing)}"


def test_the_registry_has_no_phantom_tasks() -> None:
    phantom = set(policy.POLICIES) - _load_tasks()
    assert not phantom, f"нет такой задачи в очереди: {sorted(phantom)}"


@pytest.mark.parametrize(
    ("task", "expected"),
    [
        ("inbound_mail_poll", "failed"),  # периодическая — следующий тик запустит сам
        ("external_checks_cheap", "failed"),
        ("erp_create_request", "retried"),  # идемпотентная — повтор
        ("send_email", "failed"),  # повтор = второе письмо
        ("qualify_lead", "failed"),
        ("unknown_task_without_policy", "failed"),  # без политики — никогда не повторяем
    ],
)
def test_only_declared_idempotent_tasks_are_retried(task: str, expected: str) -> None:
    assert decide(task) == expected


def test_tasks_with_a_lock_are_never_left_without_a_timeout() -> None:
    _load_tasks()
    for name, task in queue.tasks.items():
        if task.lock is not None:
            assert policy.POLICIES[name].timeout_s <= 3600, name


@pytest.mark.asyncio
async def test_a_hanging_job_is_cancelled_by_its_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(policy.POLICIES, "hang", policy.JobPolicy(policy.Kind.PERIODIC, 0.05))

    async def hang() -> Any:
        await asyncio.sleep(10)

    context = SimpleNamespace(job=SimpleNamespace(task_name="hang", id=1))
    with pytest.raises(TimeoutError):
        await policy.enforce_timeout(hang, context, None)


@pytest.mark.asyncio
async def test_a_fast_job_passes_through() -> None:
    async def fast() -> str:
        return "done"

    context = SimpleNamespace(job=SimpleNamespace(task_name="inbound_mail_poll", id=1))
    assert await policy.enforce_timeout(fast, context, None) == "done"

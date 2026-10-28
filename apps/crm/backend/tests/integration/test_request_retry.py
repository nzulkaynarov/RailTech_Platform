"""«Повторить отправку в ERP» (B-082, W16-D1-2b): заявка с ошибкой — снова `pending`, одна задача с
тем же `crm_request_id`; двойной клик — одна задача (блокировка строки); другие состояния — 409.

Мутационная проверка (описание PR): без `with_for_update` в `RequestRetryService.retry` тест
`test_double_retry_queues_one_task` красный (обе попытки видят `failed` и ставят две задачи).
"""

import asyncio
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.errors import ConflictError, NotFoundError, Reason
from app.models.auth import AuditLog
from app.models.clients import Client
from app.models.deals import Deal
from app.security.principal import Principal
from app.services.request_retry import RequestRetryService
from tests.integration.crm_helpers import make_user

pytestmark = pytest.mark.integration


class SlowQueue:
    """Подставная очередь; пауза внутри вызова расширяет окно гонки двух повторов."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, int, int]] = []

    async def __call__(self, deal_id: int, client_id: int, user_id: int) -> None:
        self.calls.append((deal_id, client_id, user_id))


async def _request(
    sessions: async_sessionmaker[AsyncSession],
    *,
    status: str | None = "failed",
    error: str | None = "erp_unavailable",
    summary: str | None = "Нужны 20 комплектов",
) -> int:
    async with sessions() as session, session.begin():
        client = Client(name="ООО Повтор")
        session.add(client)
        await session.flush()
        deal = Deal(
            client_id=client.id,
            title="Заявка: ООО Повтор",
            stage="open",
            request_summary=summary,
            erp_request_status=status,
            erp_request_error=error,
        )
        session.add(deal)
        await session.flush()
        return deal.id


async def _who(sessions: async_sessionmaker[AsyncSession]) -> Principal:
    account, _ = await make_user(sessions, "retry-manager@example.com", ["manager"])
    return Principal(account.id, "Менеджер", ("manager",))


async def test_failed_request_goes_back_to_pending_with_one_task(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _who(sessions)
    deal_id = await _request(sessions)
    queue = SlowQueue()

    result = await RequestRetryService(sessions, queue).retry(who, deal_id)

    assert result.erp_request_status == "pending"
    assert [call[0] for call in queue.calls] == [deal_id], "та же заявка — тот же crm_request_id"
    async with sessions() as session:
        deal = await session.get(Deal, deal_id)
        assert deal is not None
        assert (deal.erp_request_status, deal.erp_request_error) == ("pending", None)
        actions = (await session.scalars(select(AuditLog.action))).all()
        assert "deal.erp_request_retry" in actions


async def test_double_retry_queues_one_task(
    sessions: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Пауза между сменой статуса и коммитом (в записи аудита) — окно гонки: без блокировки строки
    обе попытки читают `failed`."""
    from app.security import audit

    original = audit.record

    async def slow_record(*args: Any, **kwargs: Any) -> None:
        await asyncio.sleep(0.3)
        await original(*args, **kwargs)

    monkeypatch.setattr(audit, "record", slow_record)
    who = await _who(sessions)
    deal_id = await _request(sessions)
    queue = SlowQueue()
    service = RequestRetryService(sessions, queue)

    results = await asyncio.gather(
        service.retry(who, deal_id), service.retry(who, deal_id), return_exceptions=True
    )

    assert len(queue.calls) == 1
    errors = [r for r in results if isinstance(r, Exception)]
    assert len(errors) == 1
    assert isinstance(errors[0], ConflictError)
    assert errors[0].details["reason"] == Reason.REQUEST_NOT_FAILED


@pytest.mark.parametrize("status", ["pending", "done", None])
async def test_request_not_in_error_is_409(
    sessions: async_sessionmaker[AsyncSession], status: str | None
) -> None:
    who = await _who(sessions)
    deal_id = await _request(sessions, status=status, error=None)
    queue = SlowQueue()

    with pytest.raises(ConflictError) as caught:
        await RequestRetryService(sessions, queue).retry(who, deal_id)

    assert caught.value.details["reason"] == Reason.REQUEST_NOT_FAILED
    assert queue.calls == []


async def test_permanent_conflict_is_not_retried(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    who = await _who(sessions)
    deal_id = await _request(sessions, error="erp_request_conflict")
    queue = SlowQueue()

    with pytest.raises(ConflictError) as caught:
        await RequestRetryService(sessions, queue).retry(who, deal_id)

    assert caught.value.details["reason"] == Reason.REQUEST_NOT_RETRYABLE
    assert "создайте заявку заново" in caught.value.message
    assert queue.calls == []


async def test_deal_without_a_request_is_404(sessions: async_sessionmaker[AsyncSession]) -> None:
    who = await _who(sessions)
    deal_id = await _request(sessions, summary=None)
    with pytest.raises(NotFoundError):
        await RequestRetryService(sessions, SlowQueue()).retry(who, deal_id)

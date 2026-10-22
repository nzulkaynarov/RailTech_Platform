"""Сквозной путь: HTTP-запрос ERP (X-Request-ID) → publish → доставка в CRM (FastAPI, приёмник) → обработчик → лог.

Корреляция переносится из запроса в конверт, в заголовки доставки, в контекст обработчика и в записи лога.
HTTP — без сети: ASGITransport вместо MockTransport.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from rt_bus import CorrelationFilter, Event, HandlerRegistry, get_correlation_id
from rt_bus.fastapi import CorrelationMiddleware, bus_router
from rt_bus.sqlalchemy import AsyncBus

from ..conftest import example_data
from .conftest import Hub

pytestmark = pytest.mark.pg

log = logging.getLogger("tests.crm.handler")


async def test_correlation_http_to_event_to_handler_to_log(
    make_bus: Callable[..., AsyncBus],
    sessions: async_sessionmaker[AsyncSession],
    hub: Hub,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # CRM: приёмник шины
    registry = HandlerRegistry()
    seen: list[tuple[str, str | None]] = []

    @registry.subscribe("uz.railtech.erp.deal.*.v1")
    async def on_deal(event: Event, session: AsyncSession) -> None:
        seen.append((event.correlationid, get_correlation_id()))
        log.info("deal mirrored")

    crm_bus = make_bus("crm", registry=registry)
    crm_app = FastAPI()
    crm_app.include_router(bus_router(lambda: crm_bus))

    # ERP: сервис с middleware корреляции, публикует событие в транзакции изменения
    erp_bus = make_bus("erp", http=httpx.AsyncClient(transport=httpx.ASGITransport(app=crm_app)))
    erp_app = FastAPI()
    erp_app.add_middleware(CorrelationMiddleware)

    @erp_app.post("/deals/905/win")
    async def win() -> dict[str, str]:
        async with sessions() as session, session.begin():
            event = await erp_bus.publish(session, "uz.railtech.erp.deal.won.v1", example_data("erp/deal.won.v1"))
        return {"event_id": event.id}

    tp = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=erp_app), base_url="http://erp") as client:
        response = await client.post("/deals/905/win", headers={"X-Request-ID": "req-e2e-1", "traceparent": tp})
    assert response.headers["x-request-id"] == "req-e2e-1"
    event_id = response.json()["event_id"]

    stats = await erp_bus.pump()
    assert (stats.relayed, stats.deliver.delivered) == (1, 1)

    caplog.handler.addFilter(CorrelationFilter())
    with caplog.at_level(logging.INFO, logger="tests.crm.handler"):
        assert await crm_bus.requeue_stuck_inbox(older_than=-1) == 1  # очереди нет — обработка здесь
    assert seen == [("req-e2e-1", "req-e2e-1")]
    [record] = [r for r in caplog.records if r.getMessage() == "deal mirrored"]
    assert record.correlation_id == "req-e2e-1"  # type: ignore[attr-defined]
    assert record.traceparent == tp  # type: ignore[attr-defined]
    [row] = await crm_bus.list_inbox()
    assert (str(row.event_id), row.correlation_id, row.status) == (event_id, "req-e2e-1", "processed")
    await erp_bus.aclose()

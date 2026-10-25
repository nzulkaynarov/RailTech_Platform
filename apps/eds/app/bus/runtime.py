"""Шина процесса EDS: `AsyncBus` сервиса `eds` с реестром обработчиков.

Секреты пар — `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>` из окружения (CRM → EDS, ERP → EDS при приёме; EDS → ERP и
EDS → platform-bff при доставке). Схемы событий и подписки — `RT_BUS_CONTRACTS_DIR` / `RT_BUS_SUBSCRIPTIONS`
(в образе — `/opt/rt/contracts`).
"""

from collections.abc import Awaitable, Callable
from typing import Any

from rt_bus import BusConfig
from rt_bus.sqlalchemy import AsyncBus
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus.handlers import build_registry

SERVICE = "eds"


def build_bus(
    sessions: Callable[[], AsyncSession],
    *,
    config: BusConfig | None = None,
    enqueue: Callable[[str], Awaitable[Any]] | None = None,
) -> AsyncBus:
    return AsyncBus(
        config or BusConfig(service=SERVICE),
        sessions,
        registry=build_registry(),
        enqueue=enqueue,
    )

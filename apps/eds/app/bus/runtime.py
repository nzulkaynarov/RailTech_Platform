"""Шина процесса EDS: `AsyncBus` сервиса `eds` с реестром обработчиков.

Секреты пар — `RT_BUS_SECRET_<ИЗДАТЕЛЬ>_<ПОДПИСЧИК>` из окружения (CRM → EDS, ERP → EDS при приёме; EDS → ERP и
EDS → platform-bff при доставке). Схемы событий и подписки — `RT_BUS_CONTRACTS_DIR` / `RT_BUS_SUBSCRIPTIONS`
(в образе — `/opt/rt/contracts`).

Пробуждение ретранслятора (B5a, `docs/architecture/rt-bus.md` §4): `wakeup` (в процессах — `tasks.wakeup`,
`app.tasks.bus`) ставит `rt_bus.pump` сразу после коммита транзакции с `publish`, а не на ближайшем тике (5 с).
Без него события уходят подписчикам только по расписанию.
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
    wakeup: Callable[[], Awaitable[Any]] | None = None,
) -> AsyncBus:
    holder: list[AsyncBus] = []  # обработчики берут шину, которая их же и вызывает
    bus = AsyncBus(
        config or BusConfig(service=SERVICE),
        sessions,
        registry=build_registry(lambda: holder[0]),
        enqueue=enqueue,
        wakeup=wakeup,
    )
    holder.append(bus)
    return bus

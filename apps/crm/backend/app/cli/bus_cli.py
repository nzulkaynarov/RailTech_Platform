"""Эксплуатация шины rt_bus из командной строки (runbook `docs/runbooks/rt-bus-crm.md`).

    python -m app bus status                       метрики: outbox, DLQ, inbox, подписчики
    python -m app bus dead [--subscriber erp]      события в DLQ (доставки `dead`)
    python -m app bus failed                       события ERP, которые CRM не смогла обработать
    python -m app bus retry <id доставки>          повторить одну доставку
    python -m app bus retry-dead [--subscriber S]  повторить все `dead` (после исправления причины)
    python -m app bus retry-inbox <id события>     повторить обработку события из inbox

Команды ничего не удаляют; повторы безопасны — приёмник гасит дубли по `id` события.
"""

import argparse
import json
import sys
from dataclasses import asdict

from app.container import get_container

ACTIONS = ("status", "dead", "failed", "retry", "retry-dead", "retry-inbox")


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument(
        "target", nargs="?", help="id доставки (retry) или id события (retry-inbox)"
    )
    parser.add_argument("--subscriber", help="только этот подписчик (dead, retry-dead)")
    parser.add_argument("--limit", type=int, default=20, help="сколько строк показать (20)")


def _print(rows: list[object]) -> None:
    for row in rows:
        sys.stdout.write(json.dumps(asdict(row), default=str, ensure_ascii=False) + "\n")  # type: ignore[call-overload]
    sys.stdout.write(f"Строк: {len(rows)}\n")


async def run(args: argparse.Namespace) -> int:
    from app.tasks.queue import queue

    container = get_container()
    bus = container.bus
    try:
        # Очередь открыта на время команды: повтор обработки ставит задачу `rt_bus.process_inbox`.
        async with queue.open_async():
            return await _dispatch(bus, args)
    finally:
        await container.aclose()


async def _dispatch(bus: object, args: argparse.Namespace) -> int:
    from app.bus.runtime import CrmBus

    assert isinstance(bus, CrmBus)  # noqa: S101 — контейнер отдаёт шину CRM
    action = args.action
    if action == "status":
        sys.stdout.write(json.dumps(asdict(await bus.metrics()), default=str, indent=2) + "\n")
    elif action == "dead":
        _print(
            list(
                await bus.list_deliveries(
                    status="dead", subscriber=args.subscriber, limit=args.limit
                )
            )
        )
    elif action == "failed":
        _print(list(await bus.list_inbox(status="failed", limit=args.limit)))
    elif action == "retry-dead":
        sys.stdout.write(f"Поставлено на повтор: {await bus.retry_all_dead(args.subscriber)}\n")
    elif not args.target:
        sys.stderr.write(
            "Нужен id: python -m app bus retry <id доставки> | retry-inbox <id события>\n"
        )
        return 2
    elif action == "retry":
        done = await bus.retry_delivery(int(args.target))
        sys.stdout.write("Поставлено на повтор.\n" if done else "Такой доставки нет.\n")
        return 0 if done else 1
    else:
        done = await bus.retry_inbox(args.target)
        sys.stdout.write(
            "Поставлено на повтор.\n" if done else "Нет записи failed/skipped с таким id.\n"
        )
        return 0 if done else 1
    return 0

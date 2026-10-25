"""Точки входа процессов: `python -m app <команда>`.

- `api` — FastAPI (REST, приёмник шины) под uvicorn;
- `worker` — воркер Procrastinate (шина: ретранслятор и обработка inbox; уборка `jti`);
- `bus status|dead|failed|retry|retry-dead|retry-inbox` — ручное управление шиной (docs/architecture/rt-bus.md §8).
"""

import argparse
import asyncio
import sys

import uvicorn

from app.config import get_settings
from app.log import configure_logging


def _run_api(args: argparse.Namespace) -> None:
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_config=None,
        access_log=False,
        proxy_headers=True,
    )


async def _run_worker() -> None:
    from app.container import get_container
    from app.tasks.queue import queue

    try:
        async with queue.open_async():
            # Периодические задачи создают по заданию на тик (pump каждые 5 с): выполненные удаляются сразу.
            await queue.run_worker_async(concurrency=get_settings().worker_concurrency, delete_jobs="successful")
    finally:
        await get_container().aclose()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app")
    commands = parser.add_subparsers(dest="command", required=True)
    api = commands.add_parser("api", help="HTTP API (FastAPI)")
    api.add_argument("--host", default="0.0.0.0")  # noqa: S104 — слушаем внутри контейнера
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--reload", action="store_true", help="hot reload (только dev)")
    commands.add_parser("worker", help="воркер Procrastinate")
    bus = commands.add_parser("bus", help="шина rt_bus: метрики, DLQ, повтор доставки и обработки")
    from app.cli import bus_cli

    bus_cli.add_arguments(bus)
    return parser


def main() -> None:
    args = _parser().parse_args()
    configure_logging(get_settings())
    if args.command == "api":
        _run_api(args)
    elif args.command == "worker":
        asyncio.run(_run_worker())
    else:
        from app.cli import bus_cli

        sys.exit(asyncio.run(bus_cli.run(args)))


if __name__ == "__main__":
    main()

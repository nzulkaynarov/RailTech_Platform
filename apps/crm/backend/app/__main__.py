"""Точки входа процессов: `python -m app api|worker`.

- `api` — FastAPI (бот, REST, auth) под uvicorn;
- `worker` — воркер Procrastinate (квалификатор, таймеры, ингест).
"""

import argparse
import asyncio

import uvicorn

from app.config import get_settings
from app.log import configure_logging


def _run_api(host: str, port: int, reload: bool) -> None:
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=host,
        port=port,
        reload=reload,
        log_config=None,
        proxy_headers=True,
    )


async def _run_worker() -> None:
    from app.tasks.queue import queue

    async with queue.open_async():
        await queue.run_worker_async()


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m app")
    commands = parser.add_subparsers(dest="command", required=True)

    api = commands.add_parser("api", help="HTTP API (FastAPI)")
    api.add_argument("--host", default="0.0.0.0")  # noqa: S104 — слушаем внутри контейнера
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--reload", action="store_true", help="hot reload (только dev)")

    commands.add_parser("worker", help="воркер Procrastinate")

    args = parser.parse_args()
    configure_logging(get_settings())
    if args.command == "api":
        _run_api(args.host, args.port, args.reload)
    else:
        asyncio.run(_run_worker())


if __name__ == "__main__":
    main()

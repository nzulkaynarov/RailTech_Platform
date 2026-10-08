"""Точки входа процессов: `python -m app <команда>`.

- `api` — FastAPI (бот, REST, auth) под uvicorn;
- `worker` — воркер Procrastinate (квалификатор, таймеры, ингест);
- `mcp kb|crm|docs` — MCP-серверы инструментов агентов;
- `kb-ingest FILE...`, `kb-demo`, `kb-eval` — база знаний (CLI для человека);
- `sample-dialogs` — выгрузка диалогов для еженедельной разметки (YAML в stdout);
- `create-admin --email ...` — первый администратор CRM.
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
        proxy_headers=True,
    )


async def _run_worker() -> None:
    from app.container import get_container
    from app.tasks.queue import queue

    try:
        async with queue.open_async():
            await queue.run_worker_async()
    finally:
        await get_container().aclose()


def _run_mcp(args: argparse.Namespace) -> None:
    from app.mcp import servers

    servers.run(args.name)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app")
    commands = parser.add_subparsers(dest="command", required=True)

    api = commands.add_parser("api", help="HTTP API (FastAPI)")
    api.add_argument("--host", default="0.0.0.0")  # noqa: S104 — слушаем внутри контейнера
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--reload", action="store_true", help="hot reload (только dev)")

    commands.add_parser("worker", help="воркер Procrastinate")

    mcp = commands.add_parser("mcp", help="MCP-сервер инструментов агента")
    mcp.add_argument("name", choices=["kb", "crm", "docs"])

    ingest = commands.add_parser("kb-ingest", help="загрузить документы в базу знаний")
    ingest.add_argument("files", nargs="+", help="пути к файлам (PDF, DOCX, PPTX, XLSX, MD, HTML)")
    ingest.add_argument("--language", choices=["ru", "uz", "en"], default="ru")
    ingest.add_argument("--product", help="ключ продукта (products.key)")
    ingest.add_argument("--title", help="заголовок (по умолчанию — имя файла)")
    ingest.add_argument("--sync", action="store_true", help="индексировать сразу, без очереди")

    admin = commands.add_parser("create-admin", help="создать/восстановить администратора CRM")
    admin.add_argument("--email", required=True)
    admin.add_argument("--name", default="Администратор")
    admin.add_argument("--password", help="пароль (по умолчанию — временный, со сменой при входе)")

    seed = commands.add_parser("seed-demo", help="демо-лиды и менеджер (dev, e2e)")
    seed.add_argument("--manager-email", default="manager@demo.local")
    seed.add_argument("--manager-password", required=True, help="пароль демо-менеджера")

    setting = commands.add_parser("settings", help="показать/изменить настройки (ключ settings)")
    setting.add_argument("key", help="ключ (company, notifications, escalation, ...) или all")
    setting.add_argument("value", nargs="?", help="JSON с полями для изменения")

    commands.add_parser("kb-demo", help="загрузить демо-базу знаний (evals/fixtures/kb)")
    commands.add_parser("kb-eval", help="проверить поиск на демо-KB (гейт Фазы 1)")
    sample = commands.add_parser("sample-dialogs", help="случайные диалоги для разметки (YAML)")
    sample.add_argument("--days", type=int, default=7, help="за сколько дней (по умолчанию 7)")
    sample.add_argument("--count", type=int, default=20, help="сколько диалогов (20)")
    sample.add_argument("--seed", type=int, default=None, help="seed для воспроизводимости")
    return parser


def main() -> None:
    args = _parser().parse_args()
    configure_logging(get_settings())
    if args.command == "api":
        _run_api(args)
    elif args.command == "worker":
        asyncio.run(_run_worker())
    elif args.command == "mcp":
        _run_mcp(args)
    else:
        sys.exit(asyncio.run(_run_cli(args)))


async def _run_cli(args: argparse.Namespace) -> int:
    if args.command == "settings":
        from app.cli import settings_cli

        return await settings_cli.run(args)
    if args.command == "seed-demo":
        from app.cli import seed_demo

        return await seed_demo.run(args)
    if args.command == "create-admin":
        from app.cli import create_admin

        return await create_admin.run(args)
    if args.command == "kb-demo":
        from app.cli import kb_demo

        return await kb_demo.run()
    if args.command == "sample-dialogs":
        from app.cli import sample_dialogs

        return await sample_dialogs.run(args)
    if args.command == "kb-eval":
        from app.cli import kb_eval

        return await kb_eval.run()
    from app.cli import kb_ingest

    return await kb_ingest.run(args)


if __name__ == "__main__":
    main()

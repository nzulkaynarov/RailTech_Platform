"""Точки входа процессов: `python -m app <команда>`.

- `api` — FastAPI (REST, auth, SSE) под uvicorn;
- `bot` — приём Telegram (polling или webhook) отдельным процессом, S0-4;
- `worker` — воркер Procrastinate (квалификатор, таймеры, ингест);
- `mcp kb|crm|docs` — MCP-серверы инструментов агентов;
- `kb-ingest FILE...`, `kb-demo`, `kb-eval` — база знаний (CLI для человека);
- `test-alert` — тестовый пост в канал (чек-лист переезда);
- `load-test` — нагрузочный smoke диалогов (Фаза 8);
- `telegram-webhook info|set|delete` — диагностика webhook prod-бота;
- `s3-mirror --dest|--restore DIR` — копия бакетов для бэкапа;
- `sample-dialogs` — выгрузка диалогов для еженедельной разметки (YAML в stdout);
- `create-admin --email ...` — первый администратор CRM;
- `litellm-seed` — модели ролей по умолчанию в БД LiteLLM (ADR-0020);
- `bus status|dead|failed|retry|retry-dead|retry-inbox` — шина rt_bus (runbook `rt-bus-crm`).
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


def _run_bot(args: argparse.Namespace) -> None:
    uvicorn.run(
        "app.bot.process:create_bot_app",
        factory=True,
        host=args.host,
        port=args.port,
        log_config=None,
        proxy_headers=True,
    )


async def _run_worker() -> None:
    from app.container import get_container
    from app.tasks.queue import queue

    try:
        async with queue.open_async():
            try:
                await queue.run_worker_async(concurrency=get_settings().worker_concurrency)
            finally:
                await get_container().drain_bus()  # пробуждения шины — пока очередь открыта
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

    bot = commands.add_parser("bot", help="бот Telegram: polling или webhook (одна реплика)")
    bot.add_argument("--host", default="0.0.0.0")  # noqa: S104 — слушаем внутри контейнера
    bot.add_argument("--port", type=int, default=8001)

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
    setting.add_argument(
        "--reset",
        action="store_true",
        help="удалить сохранённое значение ключа — вернуть значения по умолчанию",
    )

    commands.add_parser("kb-demo", help="загрузить демо-базу знаний (evals/fixtures/kb)")
    commands.add_parser("kb-eval", help="проверить поиск на демо-KB (гейт Фазы 1)")
    bus = commands.add_parser("bus", help="шина rt_bus: метрики, DLQ, повтор доставки и обработки")
    from app.cli import bus_cli

    bus_cli.add_arguments(bus)
    commands.add_parser("test-alert", help="тестовый пост в канал команды")
    commands.add_parser("litellm-seed", help="модели ролей по умолчанию в БД LiteLLM")
    load = commands.add_parser("load-test", help="нагрузочный smoke: N параллельных диалогов")
    load.add_argument("--dialogs", type=int, default=50, help="параллельных диалогов (50)")
    load.add_argument("--turns", type=int, default=3, help="вопросов в диалоге (3)")
    load.add_argument("--settle", type=int, default=60, help="пауза перед замером очереди, с")
    load.add_argument("--keep", action="store_true", help="не удалять синтетических лидов")
    load.add_argument("--yes", action="store_true", help="подтвердить расход на модели")
    hook = commands.add_parser("telegram-webhook", help="webhook бота: info | set | delete")
    hook.add_argument("action", choices=["info", "set", "delete"], nargs="?", default="info")
    mirror = commands.add_parser("s3-mirror", help="копия бакетов S3 в каталог / восстановление")
    target = mirror.add_mutually_exclusive_group(required=True)
    target.add_argument("--dest", help="каталог для выгрузки")
    target.add_argument("--restore", help="каталог копии для загрузки обратно")
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
    elif args.command == "bot":
        _run_bot(args)
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
    if args.command == "bus":
        from app.cli import bus_cli

        return await bus_cli.run(args)
    if args.command == "kb-demo":
        from app.cli import kb_demo

        return await kb_demo.run()
    if args.command == "litellm-seed":
        from app.cli import litellm_seed

        return await litellm_seed.run(args)
    if args.command == "test-alert":
        from app.cli import test_alert

        return await test_alert.run(args)
    if args.command == "load-test":
        from app.cli import load_test

        return await load_test.run(args)
    if args.command == "telegram-webhook":
        from app.cli import webhook

        return await webhook.run(args)
    if args.command == "s3-mirror":
        from app.cli import s3_mirror

        return await s3_mirror.run(args)
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

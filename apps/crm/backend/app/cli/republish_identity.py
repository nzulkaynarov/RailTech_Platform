"""Переопубликация снимков сотрудников для новых подписчиков шины (E7b, C1-G-3).

    python -m app republish-identity [--user-id N] [--dry-run]

Публикует `identity.user.updated.v1` с полным снимком (с `permissions.eds`) всем сотрудникам CRM
или одному; `--dry-run` только считает. Безопасно повторять: проекции подписчиков применяют
снимок «не старее» (runbook `rt-bus-crm`).
"""

import argparse
import sys

from app.container import get_container
from app.services.identity_republish import republish_identity


async def run(args: argparse.Namespace) -> int:
    from app.tasks.queue import queue

    container = get_container()
    try:
        # Очередь открыта на время команды: коммит с событием ставит пробуждение ретранслятора.
        async with queue.open_async():
            result = await republish_identity(
                container.session_factory, user_id=args.user_id, dry_run=args.dry_run
            )
            await container.drain_bus()  # пробуждения шины — пока очередь открыта
    finally:
        await container.aclose()
    if args.user_id is not None and result.users == 0:
        sys.stderr.write(f"Сотрудника {args.user_id} нет.\n")
        return 1
    if args.dry_run:
        sys.stdout.write(
            f"Сотрудников к переопубликации: {result.users} (dry-run, ничего не записано).\n"
        )
    else:
        sys.stdout.write(
            f"Опубликовано identity.user.updated: {result.published} из {result.users}.\n"
        )
    return 0

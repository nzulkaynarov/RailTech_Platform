"""Republish contact snapshots of clients already handed over to ERP (people audit G2, 2026-11-24).

    python -m app republish-contacts [--client-id N] [--apply]

ERP skipped `contact.created` while the client was not handed over, so the position and the
Telegram username of the contacts never arrived. Without `--apply` the command only counts. Safe to
repeat: ERP applies a snapshot of the same moment once and skips an equal one.
"""

import argparse
import sys

from app.container import get_container
from app.services.client_republish import republish_handed_over_contacts


async def run(args: argparse.Namespace) -> int:
    from app.tasks.queue import queue

    container = get_container()
    try:
        # The queue is open for the command: the commit wakes the relay.
        async with queue.open_async():
            result = await republish_handed_over_contacts(
                container.session_factory, client_id=args.client_id, dry_run=not args.apply
            )
            await container.drain_bus()
    finally:
        await container.aclose()
    if not args.apply:
        sys.stdout.write(
            f"Переданных клиентов: {result.clients}, контактов к переопубликации: "
            f"{result.contacts}; телефонов к приведению к E.164: {result.phones_to_fix}, "
            f"не приводятся (контакт не публикуется): {result.phones_unparseable} "
            "(dry-run, ничего не записано; для записи --apply).\n"
        )
    else:
        sys.stdout.write(
            f"Опубликовано contact.updated: {result.published} (клиентов: {result.clients}); "
            f"телефонов приведено: {result.phones_to_fix}, не приводятся: "
            f"{result.phones_unparseable}.\n"
        )
    return 0

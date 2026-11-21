"""Republish client snapshots for consumers that missed them (W21, PR #763 follow-up).

    python -m app republish-clients [--client-id N] [--dry-run]

Publishes `client.updated.v1` with the full current snapshot (with `owner`) for every client or
one; `--dry-run` only counts. Safe to repeat: consumers replace their projection by the snapshot
(runbook `rt-bus-crm`).
"""

import argparse
import sys

from app.container import get_container
from app.services.client_republish import republish_clients


async def run(args: argparse.Namespace) -> int:
    from app.tasks.queue import queue

    container = get_container()
    try:
        # The queue is open for the command: the commit wakes the relay.
        async with queue.open_async():
            result = await republish_clients(
                container.session_factory, client_id=args.client_id, dry_run=args.dry_run
            )
            await container.drain_bus()
    finally:
        await container.aclose()
    if args.client_id is not None and result.clients == 0:
        sys.stderr.write(f"Клиента {args.client_id} нет.\n")
        return 1
    if args.dry_run:
        sys.stdout.write(
            f"Клиентов к переопубликации: {result.clients} (dry-run, ничего не записано).\n"
        )
    else:
        sys.stdout.write(f"Опубликовано client.updated: {result.published} из {result.clients}.\n")
    return 0

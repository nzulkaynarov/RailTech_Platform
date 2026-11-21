"""Перенумерация копий номеров CRM в латиницу (СЦ-5), одноразово.

    python -m app renumber-latin MAPPING.json          # сухой прогон: «было → станет»
    python -m app renumber-latin - --apply < MAPPING.json

Маппинг общий для всех систем: `{"ВХ-001/26": "IN-001/26", ...}`. Без `--apply` ничего не пишется;
с ним — одна транзакция, повтор ничего не меняет.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from app.container import get_container
from app.services import renumber_latin as svc


async def run(args: argparse.Namespace) -> int:
    try:
        path = Path(args.mapping)
        raw = (
            sys.stdin.read()
            if args.mapping == "-"
            else await asyncio.to_thread(path.read_text, "utf-8")
        )
        mapping = svc.parse_mapping(raw)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"Ошибка: {exc}\n")
        return 1
    container = get_container()
    try:
        async with container.session_factory() as session, session.begin():
            if args.apply:
                changed = await svc.apply(session, mapping)
                sys.stdout.write(f"Применено: {changed} изменений.\n")
            else:
                changes = await svc.plan(session, mapping)
                for change in changes:
                    sys.stdout.write(change.line() + "\n")
                sys.stdout.write(f"Сухой прогон: {len(changes)} изменений, запись — с --apply.\n")
    finally:
        await container.aclose()
    return 0

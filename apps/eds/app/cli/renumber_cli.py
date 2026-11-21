"""Разовая перенумерация на латиницу (СЦ-5), только таблицы EDS (`app/services/renumber.py`).

    python -m app renumber-latin map.json            сухой прогон: «таблица.колонка id: было → станет»
    python -m app renumber-latin map.json --apply    записать всё одной транзакцией (повтор ничего не меняет)
    python -m app renumber-latin - < map.json        карта со стандартного ввода
    python -m app renumber-latin --emit-mapping      карта СВОИХ номеров EDS по действующим обозначениям (JSON)

Карта — плоский JSON `{"ВХ-001/26": "IN-001/26", ...}`, общая для всех систем: лишние ключи игнорируются.
"""

import argparse
import json
import sys
from pathlib import Path

from app.container import Container, get_container
from app.services import renumber


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("mapping", nargs="?", help="файл карты {старый: новый} или «-» (стандартный ввод)")
    parser.add_argument("--apply", action="store_true", help="записать (без флага — сухой прогон)")
    parser.add_argument("--emit-mapping", action="store_true", help="напечатать карту своих номеров EDS и выйти")


def _load(source: str) -> dict[str, str]:
    raw = sys.stdin.read() if source == "-" else Path(source).read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in data.items()):
        raise SystemExit("Карта — плоский JSON-объект {«старый номер»: «новый номер»}.")
    return data


async def run(args: argparse.Namespace, container: Container | None = None) -> int:
    own = container is None
    box = container or get_container()
    try:
        async with box.session_factory() as session:
            if args.emit_mapping:
                mapping = await renumber.emit_mapping(session)
                sys.stdout.write(json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
                return 0
            if not args.mapping:
                raise SystemExit("Укажите файл карты, «-» или --emit-mapping.")
            plan = await renumber.build_plan(session, _load(args.mapping))
            for change in plan.changes:
                sys.stdout.write(change.line() + "\n")
            for error in plan.errors:
                sys.stderr.write(f"ОШИБКА: {error}\n")
            if plan.errors:
                return 2
            if not args.apply:
                sys.stdout.write(f"Сухой прогон: изменений {len(plan.changes)}; записать — --apply.\n")
                return 0
            await renumber.apply_plan(session, plan)
            await session.commit()  # всё одной транзакцией
            sys.stdout.write(f"Записано: изменений {len(plan.changes)}.\n")
            return 0
    finally:
        if own:
            await box.aclose()

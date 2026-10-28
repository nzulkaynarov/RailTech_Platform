#!/usr/bin/env python3
"""Сводка и проверка реестра хвостов docs/BACKLOG.md (решение владельца 2026-10-28: без очереди номеров).

    python3 scripts/backlog.py          сводка: всего, по приоритету, по типу и приоритету (make docs-backlog)
    python3 scripts/backlog.py --check  только проверка: ID уникальны и по формату (входит в scripts/check-doc-links.sh)

Сводных счётчиков в BACKLOG.md руками не ведут: их правил каждый PR, и параллельные PR конфликтовали. Счёт — здесь.
ID строки — прежний `B-NNN` (B-001…B-087, не меняются) или новый `B-<задача>-<n>` (`B-D24-1`, `B-W15H8b-2`):
номер не глобальный, поэтому два PR не берут один и тот же. Две строки с одним ID (git сливает их молча) — ошибка.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

BACKLOG = Path(__file__).resolve().parent.parent / "docs" / "BACKLOG.md"
ID_RE = re.compile(r"^B-(\d{3}|[A-Za-z0-9]+-\d+)$")
COLUMNS = ("ID", "Что", "Откуда", "Зона", "Тип", "Приоритет", "План")


def rows(text: str) -> list[dict[str, str]]:
    """Строки таблицы раздела «## Реестр» (до следующего заголовка второго уровня)."""
    out: list[dict[str, str]] = []
    in_registry = False
    for line in text.splitlines():
        if line.startswith("## "):
            in_registry = line.strip() == "## Реестр"
            continue
        if not in_registry or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if cells[0] in ("ID", "") or set(cells[0]) <= {"-", ":"}:
            continue
        out.append(dict(zip(COLUMNS, cells, strict=False)))
    return out


def check(items: list[dict[str, str]]) -> list[str]:
    errors: list[str] = []
    for item in items:
        if not ID_RE.match(item["ID"]):
            errors.append(f"ID {item['ID']!r} не по формату: B-NNN (старые) или B-<задача>-<n>, например B-D24-1")
    for rid, n in Counter(i["ID"] for i in items).items():
        if n > 1:
            errors.append(f"ID {rid} встречается {n} раза — у новой строки свой ID B-<задача>-<n>")
    return errors


def summary(items: list[dict[str, str]]) -> str:
    prio = Counter(i.get("Приоритет", "?") for i in items)
    lines = [f"Всего хвостов: {len(items)} — " + ", ".join(f"{p}: {prio.get(p, 0)}" for p in ("P0", "P1", "P2"))]
    by_type: dict[str, Counter[str]] = {}
    for i in items:
        by_type.setdefault(i.get("Тип", "?"), Counter())[i.get("Приоритет", "?")] += 1
    lines.append("")
    lines.append(f"{'Тип':<14} {'P0':>3} {'P1':>3} {'P2':>3}")
    for kind in sorted(by_type):
        c = by_type[kind]
        lines.append(f"{kind:<14} {c.get('P0', 0):>3} {c.get('P1', 0):>3} {c.get('P2', 0):>3}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    items = rows(BACKLOG.read_text(encoding="utf-8"))
    errors = check(items)
    for e in errors:
        print(f"docs/BACKLOG.md: {e}", file=sys.stderr)
    if "--check" not in argv:
        print(summary(items))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

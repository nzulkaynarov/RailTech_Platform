#!/usr/bin/env python3
"""Таблица задержек «коммит события -> доставка подписчику» по фазам замера W13-A0.

    latency_table.py <rows.csv> <phases.txt>

rows.csv — вывод ../../w11c-gate/logs/collect_latency.sh (`издатель|подписчик|тип|outbox.created_at|delivered_at|попыток`),
phases.txt — строки `имя|начало|конец|slow` (UTC, `YYYY-MM-DD HH:MM:SS`; slow = 1, если в фазе подписчик `slow` отвечает 2,5 с).
Печатает по каждой фазе: подписчик × (n, p50, p95, max, не с 1-й попытки) — по всем издателям и по каждому отдельно.
Критерий (фазы со slow=1): у быстрых подписчиков (все, кроме `slow`) p95 <= 2000 мс и max <= 3000 мс.
Перцентили — линейная интерполяция, как в ../../w11c-gate/logs/latency_stats.py (оттуда parse и pct).
"""
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "w11c-gate", "logs"))
from latency_stats import parse, pct  # noqa: E402

P95_MS, MAX_MS = 2000, 3000


def main(rows_path: str, phases_path: str) -> int:
    rows = []
    for line in open(rows_path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        pub, sub, typ, created, delivered, attempts = line.split("|")
        rows.append((pub, sub, parse(created.replace(" ", "T")), parse(delivered.replace(" ", "T")) if delivered else None, int(attempts)))
    ok_all = True
    for spec in open(phases_path, encoding="utf-8"):
        spec = spec.strip()
        if not spec or spec.startswith("#"):
            continue
        name, start, end, slow = spec.split("|")
        lo, hi = parse(start.replace(" ", "T")), parse(end.replace(" ", "T"))
        groups: dict[tuple[str, str], list[float]] = defaultdict(list)
        retried: dict[tuple[str, str], int] = defaultdict(int)
        undelivered = 0
        for pub, sub, created, delivered, attempts in rows:
            if not lo <= created < hi:
                continue
            if delivered is None:
                undelivered += 1
                continue
            ms = (delivered - created).total_seconds() * 1000
            for key in ((pub, sub), ("*", sub)):
                groups[key].append(ms)
                if attempts > 1:
                    retried[key] += 1
        print(f"\n## Фаза «{name}» {start} .. {end} UTC, slow={'да' if slow == '1' else 'нет'}, недоставлено на момент выгрузки: {undelivered}")
        print(f"{'издатель':9} {'подписчик':13} {'n':>5} {'p50 мс':>9} {'p95 мс':>9} {'max мс':>9} {'не с 1-й':>9}")
        phase_ok = True
        for key in sorted(groups, key=lambda k: (k[1], k[0])):
            v = sorted(groups[key])
            fast = key[1] != "slow"
            mark = ""
            if fast and slow == "1" and key[0] == "*":
                good = pct(v, 0.95) <= P95_MS and v[-1] <= MAX_MS
                mark = "  OK" if good else "  НАРУШЕНИЕ"
                phase_ok &= good
            print(f"{key[0]:9} {key[1]:13} {len(v):5d} {pct(v, .5):9.0f} {pct(v, .95):9.0f} {v[-1]:9.0f} {retried[key]:9d}{mark}")
        if slow == "1":
            print(f"критерий фазы (быстрые подписчики по всем издателям: p95 <= {P95_MS} мс, max <= {MAX_MS} мс):", "ВЫПОЛНЕН" if phase_ok else "НЕ ВЫПОЛНЕН")
            ok_all &= phase_ok
    print("\nИТОГ:", "критерий выполнен во всех фазах со slow" if ok_all else "критерий НЕ выполнен")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))

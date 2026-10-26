#!/usr/bin/env python3
"""Задержка «коммит события -> доставка подписчику» по строкам rt_bus_outbox x rt_bus_delivery (гейт 11c, пункт 3).

Вход (stdin или файл): CSV без заголовка, разделитель «|»:
    издатель|подписчик|тип события|outbox.created_at|delivery.delivered_at|попыток
Времена — ISO 8601 (UTC). Вывод: по каждому (издатель, подписчик) — n, p50, p95, max (мс), число доставок не с первой попытки,
и отдельно «все подписчики» по издателю. Перцентили — линейная интерполяция (как numpy.percentile).
Критерий гейта: p95 и max до platform-bff <= 2000 мс.
"""
import sys
from collections import defaultdict
from datetime import datetime


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.strip().replace("Z", "+00:00"))


def pct(sorted_vals, q):
    if not sorted_vals:
        return float("nan")
    k = (len(sorted_vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (k - lo)


def main(lines):
    groups = defaultdict(list)
    retried = defaultdict(int)
    for line in lines:
        line = line.strip()
        if not line:
            continue
        pub, sub, typ, created, delivered, attempts = line.split("|")
        if not delivered:
            continue
        ms = (parse(delivered) - parse(created)).total_seconds() * 1000
        for key in ((pub, sub), (pub, "*")):
            groups[key].append(ms)
            if int(attempts) > 1:
                retried[key] += 1
    print(f"{'издатель':9} {'подписчик':13} {'n':>5} {'p50 мс':>9} {'p95 мс':>9} {'max мс':>9} {'не с 1-й':>9}")
    for key in sorted(groups):
        v = sorted(groups[key])
        print(f"{key[0]:9} {key[1]:13} {len(v):5d} {pct(v, .5):9.0f} {pct(v, .95):9.0f} {v[-1]:9.0f} {retried[key]:9d}")
    bff = {k: sorted(v) for k, v in groups.items() if k[1] == "platform-bff"}
    ok = all(pct(v, .95) <= 2000 and v[-1] <= 2000 for v in bff.values()) if bff else False
    print("критерий (p95 и max до platform-bff <= 2000 мс по каждому издателю):", "ВЫПОЛНЕН" if ok else "НЕ ВЫПОЛНЕН")


if __name__ == "__main__":
    main(open(sys.argv[1]) if len(sys.argv) > 1 else sys.stdin)

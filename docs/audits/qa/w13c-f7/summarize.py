#!/usr/bin/env python3
"""Сводка A/B-замера W13C-F7 по каталогам прогонов (rows.csv, phases.txt, load.txt, foreign.txt из measure_ab.sh).

    summarize.py <каталог_логов> A1 B1 A2 B2 A3 B3

Печатает markdown: p95/max быстрых подписчиков по фазам x1 и burst (все издатели), load average (1 мин: min..max за прогон),
недоставленные / доставки не с 1-й попытки / dead, задержку slow, признак загрязнения. Перцентили — как в latency_stats.py.
"""
import os
import re
import sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "..", "screens", "w11c-gate", "logs"))
from latency_stats import parse, pct  # noqa: E402

FAST = ["platform-bff", "crm", "erp", "eds"]
P95, MAXMS = 2000, 3000


def load_run(d):
    rows = []
    for line in open(os.path.join(d, "rows.csv"), encoding="utf-8"):
        line = line.strip()
        if line:
            pub, sub, typ, c, dl, at = line.split("|")
            rows.append((pub, sub, parse(c.replace(" ", "T")), parse(dl.replace(" ", "T")) if dl else None, int(at)))
    phases = {}
    for line in open(os.path.join(d, "phases.txt"), encoding="utf-8"):
        if line.strip():
            n, a, b, _ = line.strip().split("|")
            phases[n] = (parse(a.replace(" ", "T")), parse(b.replace(" ", "T")))
    loads = []
    for line in open(os.path.join(d, "load.txt"), encoding="utf-8"):
        m = re.search(r"(\d+[.,]\d+)[ ,]+(\d+[.,]\d+)[ ,]+(\d+[.,]\d+)\s*$", line)
        if m:
            loads.append(float(m.group(1).replace(",", ".")))
    foreign = os.path.getsize(os.path.join(d, "foreign.txt")) > 0
    return rows, phases, loads, foreign


def stats(rows, phase, sub, lo, hi):
    v = sorted((dl - c).total_seconds() * 1000 for p, s, c, dl, a in rows if s == sub and dl and lo <= c < hi)
    if not v:
        return None
    return pct(v, 0.95), v[-1], len(v)


def main(root, names):
    out = defaultdict(dict)
    head = ["Прогон", "load 1 мин (min..max)", "фаза"] + FAST + ["slow p50/p95/max", "недост.", "не с 1-й", "чисто"]
    print("| " + " | ".join(head) + " |")
    print("|" + "---|" * len(head))
    for name in names:
        rows, phases, loads, foreign = load_run(os.path.join(root, name))
        lo_all, hi_all = min(r[2] for r in rows), max(p[1] for p in phases.values())
        undel = sum(1 for r in rows if r[3] is None and phases["control"][0] <= r[2] < hi_all)
        retried = sum(1 for r in rows if r[4] > 1)
        sl = sorted((r[3] - r[2]).total_seconds() * 1000 for r in rows if r[1] == "slow" and r[3])
        slow = f"{pct(sl, .5):.0f}/{pct(sl, .95):.0f}/{sl[-1]:.0f} (n={len(sl)})" if sl else "—"
        ld = f"{min(loads):.1f}..{max(loads):.1f}" if loads else "?"
        for ph in ("x1", "burst"):
            lo, hi = phases[ph]
            cells = []
            for sub in FAST:
                s = stats(rows, ph, sub, lo, hi)
                if s is None:
                    cells.append("—")
                    continue
                bad = s[0] > P95 or s[1] > MAXMS
                cells.append(f"{s[0]:.0f}/{s[1]:.0f}" + (" **!**" if bad else "") + f" (n={s[2]})")
            first = ph == "x1"
            print("| " + " | ".join([name if first else "", ld if first else "", ph] + cells + [slow if first else "", str(undel) if first else "", str(retried) if first else "", ("нет" if foreign else "да") if first else ""]) + " |")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])

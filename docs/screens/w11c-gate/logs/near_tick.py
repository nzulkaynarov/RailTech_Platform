#!/usr/bin/env python3
"""Из CSV (формат latency_stats.py) на stdin — события, созданные у периодического тика pump (фаза created_at по модулю 5 с в [4.7, 5) или [0, 0.4]),
доставка platform-bff. Печатает n, p50, p95, max (мс). Аргументы: издатель."""
import sys
from datetime import datetime
pub = sys.argv[1] if len(sys.argv) > 1 else "crm"
near, other = [], []
for l in sys.stdin:
    r = l.strip().split("|")
    if len(r) < 6 or r[0] != pub or r[1] != "platform-bff" or not r[4]:
        continue
    c, d = datetime.fromisoformat(r[3]), datetime.fromisoformat(r[4])
    ph = c.second % 5 + c.microsecond / 1e6
    ms = (d - c).total_seconds() * 1000
    (near if (ph >= 4.7 or ph <= 0.4) else other).append(ms)
def show(name, v):
    v = sorted(v)
    if not v: print(name, "n=0"); return
    p95 = v[min(len(v) - 1, int(round((len(v) - 1) * .95)))]
    print(f"{name}: n={len(v)} p50={v[len(v)//2]:.0f} p95={p95:.0f} max={v[-1]:.0f} мс")
show("у тика (фаза [4.7,5)∪[0,0.4] с)", near)
show("вне тика", other)

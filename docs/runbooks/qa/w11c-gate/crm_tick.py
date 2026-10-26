"""Лиды CRM, привязанные к периодическому тику pump (cron каждые 5 с): запуск в момент t = k*5 с + смещение из [-0.25, +0.35] с.
Цель — события, совпадающие с поставленной, но ещё не стартовавшей периодической задачей (W11B-G-6). Аргумент: N"""
import random, sys, time
from c1lib import *

N = int(sys.argv[1]) if len(sys.argv) > 1 else 20
st = load()
tok = crm_token(st, "manager")
offs = []
for i in range(N):
    off = random.uniform(-0.25, 0.35)
    now = time.time()
    tick = (int(now // 5) + 1) * 5
    target = tick + off
    if target - now < 0.4:
        target += 5
    time.sleep(target - time.time())
    c, b, _ = req("POST", CRM + "/api/v1/leads", {"source": "phone", "name": f"Тик {i}", "phone": f"+99893{random.randint(1000000,9999999)}", "need": "лид у тика", "language": "ru"}, token=tok)
    if c == 201:
        req("POST", CRM + f"/api/v1/leads/{b['id']}/actions/take", {}, token=tok)
    offs.append(round(time.time() % 5, 2))
print("crm_tick: лидов", N, "фаза внутри 5-секундного тика (с):", sorted(offs)[:5], "...", sorted(offs)[-5:])

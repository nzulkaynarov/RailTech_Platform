"""Генератор событий EDS: входящие письма (eds.letter.registered). Аргументы: N пауза_с"""
import random, sys
from c1lib import *

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
PAUSE = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
st = load()
tok, _ = eds_token(crm_token(st, "director"))
ok = 0
for i in range(N):
    key = f"w11c-let-{time.time_ns()}-{i}"
    c, b, _ = eds("POST", "/api/v1/letters", tok, {"subject": f"Письмо гейта {i}", "summary": "нагрузочное письмо", "sender": {"name": f"Отправитель {i}", "inn": None}, "received_at": "2026-10-26"}, headers={"Idempotency-Key": key})
    ok += c == 201
    time.sleep(random.uniform(0, PAUSE * 2))
print("eds_gen registered", ok, "of", N)

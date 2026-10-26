"""Генератор событий CRM: лид (lead.created) -> взять в работу (lead.updated). Аргументы: N потоков_параллельно пауза_с
Потоки стартуют по барьеру: все публикации одновременно."""
import sys, threading, time, random
from c1lib import *

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5
PAR = int(sys.argv[2]) if len(sys.argv) > 2 else 1
PAUSE = float(sys.argv[3]) if len(sys.argv) > 3 else 0.5
st = load()
tok = crm_token(st, "manager")
bar = threading.Barrier(PAR)
res = []
lock = threading.Lock()

def work(k):
    bar.wait()
    for i in range(N):
        t0 = time.time()
        c, b, _ = req("POST", CRM + "/api/v1/leads", {"source": "phone", "name": f"Нагрузка {k}-{i}", "phone": f"+99891{random.randint(1000000,9999999)}", "need": "нагрузочный лид гейта", "language": "ru"}, token=tok)
        c2 = None
        if c == 201:
            c2, _, _ = req("POST", CRM + f"/api/v1/leads/{b['id']}/actions/take", {}, token=tok)
        with lock:
            res.append((c, c2, time.time() - t0))
        time.sleep(random.uniform(0, PAUSE * 2))

th = [threading.Thread(target=work, args=(k,)) for k in range(PAR)]
[t.start() for t in th]
[t.join() for t in th]
from collections import Counter
print("crm_gen leads", Counter((a, b) for a, b, _ in res), "max_s=%.2f" % max(x for _, _, x in res))

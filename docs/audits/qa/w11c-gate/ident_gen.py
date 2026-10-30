"""Генератор событий для подписчиков `erp` и `eds` (добавлен в W13-A0): правка клиента CRM (crm.client.updated -> erp, platform-bff)
и правка сотрудника (identity.user.updated -> eds, platform-bff). Аргументы: N правок_на_поток ПОТОКОВ пауза_с
Потоки стартуют по барьеру: все публикации одновременно. Запуск: run.sh ident_gen.py 1 25 0.0"""
import random
import sys
import threading
import time
from collections import Counter

from c1lib import *

N = int(sys.argv[1]) if len(sys.argv) > 1 else 1
PAR = int(sys.argv[2]) if len(sys.argv) > 2 else 1
PAUSE = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
st = load()
tok = crm_token(st, "admin")          # правка сотрудников
tok_mgr = crm_token(st, "manager")    # правка клиента (у администратора права на клиентов нет — 403)
user_ids = [u["id"] for k, u in st["users"].items() if k != "admin" and "id" in u]
client_id = (st.get("req", {}).get("1") or {}).get("client", 1)
bar = threading.Barrier(PAR)
res, lock = [], threading.Lock()


def work(k):
    bar.wait()
    for i in range(N):
        if (k + i) % 2 == 0:   # клиент -> erp
            c, _, _ = req("PATCH", CRM + f"/api/v1/clients/{client_id}", {"name": f"ООО «Демо Заказчик 1» {k}-{i}-{random.randint(1, 10**6)}"}, token=tok_mgr)
            kind = "client"
        else:                  # сотрудник -> eds
            uid = user_ids[(k + i) % len(user_ids)]
            c, _, _ = req("PATCH", CRM + f"/api/v1/users/{uid}", {"full_name": f"Сотрудник Демо {uid}-{random.randint(1, 10**6)}"}, token=tok)
            kind = "user"
        with lock:
            res.append((kind, c))
        time.sleep(random.uniform(0, PAUSE * 2))


th = [threading.Thread(target=work, args=(k,)) for k in range(PAR)]
[t.start() for t in th]
[t.join() for t in th]
print("ident_gen", Counter(res))

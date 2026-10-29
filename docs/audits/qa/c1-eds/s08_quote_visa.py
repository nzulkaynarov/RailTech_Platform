"""Пункт 5 (часть Б): инженер визирует КП в ERP -> ERP публикует quote.ready_for_approval -> маршрут «КП» в EDS."""
import sys
from c1lib import *

st = load()
KEY = sys.argv[2] if len(sys.argv) > 2 else "quote"
qid = st[KEY]["id"]
eng = erp_token(crm_token(st, "engineer"))
step = int(sys.argv[1])
t0 = time.time()
c, q, _ = req("POST", ERP + f"/api/v1/crm/quotes/{qid}/approval-act/", {"step_id": step, "decision": "APPROVE", "comment": "расчёт услуг проверен"}, token=eng)
print("visa", c, (q.get("number"), q.get("status")) if isinstance(q, dict) else q, f"t={t0}")
st[KEY]["t_visa"] = t0
save(st)

"""Пункт 6: GET КП в ERP (C1-G-5) и отправка клиенту разными ролями (C1-G-4). Аргументы: ключ_КП  роль_отправителя,...  (порядок попыток)"""
import sys
from c1lib import *

key = sys.argv[1]
who = sys.argv[2].split(",")
st = load()
qid = st[key]["id"]
H = ERP + "/api/v1/crm/"
mgr = erp_token(crm_token(st, "manager"))
c, q, _ = req("GET", H + f"quotes/{qid}/", token=mgr)
print("GET КП в ERP", c, {k: q.get(k) for k in ("number", "status", "outgoing_number", "director_decision", "director_comment", "director_decided_at", "send_channels", "eds_revision") if k in q})
print("   поля ответа про директора/ИСХ:", sorted(k for k in q if "director" in k or "outgoing" in k))
for w in who:
    tok = erp_token(crm_token(st, w))
    c, b, _ = req("POST", H + f"quotes/{qid}/send-to-client/", {}, token=tok)
    print(f"send-to-client от {w}:", c, json.dumps(b, ensure_ascii=False)[:260] if c != 200 else {"status": b.get("status_code") or b.get("status"), "frozen": bool(b.get("frozen_at"))})

"""Пункт 5 (часть Г): после возврата снабженец правит КП (цена строки) и отправляет повторно; если нужна виза инженера — он визирует."""
import sys
from c1lib import *

KEY = sys.argv[1] if len(sys.argv) > 1 else "quote"
PATCH_ = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {"quantity": 420}   # правка первой строки

st = load()
qid = st[KEY]["id"]
sup = erp_token(crm_token(st, "supply"))
eng = erp_token(crm_token(st, "engineer"))
H = ERP + "/api/v1/crm/"
c, q, _ = req("GET", H + f"quotes/{qid}/", token=sup)
print("КП до правки: status", q.get("status"), "director_comment:", q.get("director_comment"), "decision:", q.get("director_decision"))
c, items, _ = req("GET", H + f"quote-items/?quote={qid}", token=sup)
rows = items["results"] if isinstance(items, dict) and "results" in items else items
first = rows[0]
c, b, _ = req("PATCH", H + f"quote-items/{first['id']}/", PATCH_, token=sup)
print("правка первой строки:", c, "" if c == 200 else b)
c, sub, _ = req("POST", H + f"quotes/{qid}/submit-for-review/", {}, token=sup)
print("повторная отправка:", c, (sub.get("number"), sub.get("status")) if isinstance(sub, dict) else sub)
print("статус после:", sub.get("status") if isinstance(sub, dict) else None)

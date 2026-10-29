"""Пункт 5 (часть А): снабженец собирает КП в ERP на сделке с заданием расчёта, отправляет на согласование; инженер визирует."""
import sys
from c1lib import *

DEAL = int(sys.argv[1]) if len(sys.argv) > 1 else 1          # сделка ERP
MARGIN_ITEM = sys.argv[2] if len(sys.argv) > 2 else "30.00"  # наценка строк, %
KEY = sys.argv[3] if len(sys.argv) > 3 else "quote"          # ключ в состоянии

st = load()
sup = erp_token(crm_token(st, "supply"))
eng = erp_token(crm_token(st, "engineer"))
H = ERP + "/api/v1/crm/"
deal = DEAL
c, q, _ = req("POST", H + "quotes/", {"deal": deal}, token=sup)
print("create quote", c, (q.get("id"), q.get("version"), q.get("status")) if isinstance(q, dict) else q)
qid = q["id"]
items = [
    {"quote": qid, "imported_raw_name": "Накладка 4-дырная Р65 (демо)", "quantity": 400, "unit": "шт.", "frozen_base_price": "1000.00", "frozen_currency": "UZS", "margin_percent": MARGIN_ITEM},
    {"quote": qid, "imported_raw_name": "Монтаж и шефмонтаж (демо)", "quantity": 1, "unit": "усл.", "frozen_base_price": "50000.00", "frozen_currency": "UZS", "margin_percent": MARGIN_ITEM},
]
for it in items:
    c, b, _ = req("POST", H + "quote-items/", it, token=sup)
    print("item", c, "" if c == 201 else b)
c, q, _ = req("GET", H + f"quotes/{qid}/", token=sup)
print("quote totals: subtotal", q.get("subtotal_excl_vat"), "total", q.get("total_incl_vat"), "margin%", q.get("margin_percent"), "status", q["status"] if "status" in q else None)
c, pv, _ = req("GET", H + f"quotes/{qid}/approval-preview/", token=sup)
print("approval-preview", c, json.dumps(pv, ensure_ascii=False)[:500])
c, sub, _ = req("POST", H + f"quotes/{qid}/submit-for-review/", {}, token=sup)
print("submit-for-review", c, (sub.get("status"), sub.get("number")) if isinstance(sub, dict) else sub, json.dumps(sub, ensure_ascii=False)[:300] if c != 200 else "")
st[KEY] = {"id": qid, "deal": DEAL}
save(st)

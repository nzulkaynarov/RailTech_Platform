"""Пункт 5 (часть В): директор открывает маршрут «КП» в EDS (чек-лист), решает. Аргумент: approve | return | reject; для return — текст комментария."""
import sys
from c1lib import *

st = load()
decision = sys.argv[1]
comment = sys.argv[2] if len(sys.argv) > 2 else None
dt, _ = eds_token(crm_token(st, "director"))
c, lst, _ = eds("GET", "/api/v1/approvals?mine=1", dt)
quotes = [a for a in lst["items"] if a["template"] == "quote" and a["status"] == "open"]
print("очередь директора (КП):", [(a["id"], a["title"], a["round"]) for a in quotes])
a0 = quotes[-1]
c, a, _ = eds("GET", f"/api/v1/approvals/{a0['id']}", dt)
print("шаги:", [(s["index"], s["label"], s["status"]) for s in a["steps"]])
print("чек-лист:", json.dumps(a["checklist"], ensure_ascii=False))
print("снимок КП (ключи):", sorted((a["quote"] or {}).keys()))
print("can_decide:", a["can_decide"], "allowed:", a["allowed_decisions"], "round:", a["round"])
body = {"decision": decision}
if comment:
    body["comment"] = comment
if decision == "approve":
    body["channels"] = ["email"]
t0 = time.time()
c, r, _ = eds("POST", f"/api/v1/approvals/{a0['id']}/decision", dt, body)
print("decision", decision, "->", c, (r.get("status"), r.get("outgoing_number")) if isinstance(r, dict) and c == 200 else r)
st["quote_route"] = {"id": a0["id"], "t_decision": t0, "decision": decision}
save(st)

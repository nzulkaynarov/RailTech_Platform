"""Пункт 6: решение директора по маршруту КП (с выбором маршрута по номеру КП): approve | return | reject [комментарий]; печатает тело ответа целиком при ошибке."""
import sys
from c1lib import *

num, decision = sys.argv[1], sys.argv[2]
comment = sys.argv[3] if len(sys.argv) > 3 else None
st = load()
dt, _ = eds_token(crm_token(st, "director"))
c, lst, _ = eds("GET", "/api/v1/approvals?mine=1", dt)
route = [a for a in lst["items"] if a["template"] == "quote" and a["status"] == "open" and num in a["title"]][-1]
c, a, _ = eds("GET", f"/api/v1/approvals/{route['id']}", dt)
print("маршрут", route["title"], "| чек-лист:", [(i["code"], "ok" if i["ok"] else "RED", "блок" if i["blocking"] else "предупр.", i["value"]) for i in a["checklist"]], "| allowed:", a["allowed_decisions"])
body = {"decision": decision}
if comment: body["comment"] = comment
if decision == "approve": body["channels"] = ["email"]
c, r, _ = eds("POST", f"/api/v1/approvals/{route['id']}/decision", dt, body)
print("решение", decision, "->", c, json.dumps(r, ensure_ascii=False)[:420] if c != 200 else (r.get("status"), r.get("outgoing_number"), "approved_late=" + str(r.get("approved_late"))))
print("route_id", route["id"])

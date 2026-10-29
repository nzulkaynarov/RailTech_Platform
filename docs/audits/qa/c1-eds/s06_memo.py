"""Пункт 4: служебная записка с суммой (автор -> директор -> бухгалтер) и без суммы (только директор)."""
from c1lib import *

st = load()
tok = {}
for k in ("manager", "director", "mgr_acc"):
    tok[k], _ = eds_token(crm_token(st, k))


def show(c, b, keys=("id", "number", "status", "kind")):
    return c, {k: b.get(k) for k in keys} if isinstance(b, dict) else b


def steps(a):
    return [(s["index"], s["label"], s["status"], (s["decided_by"] or {}).get("full_name")) for s in a["steps"]]


# --- с суммой
c, d, _ = eds("POST", "/api/v1/documents", tok["manager"], {"kind": "memo", "subject": "Оплата аренды склада (демо)", "text": "Прошу согласовать оплату аренды склада за ноябрь.", "amount": {"amount": "12500000.00", "currency": "UZS"}}, headers={"Idempotency-Key": "c1-memo-amount-1"})
print("create memo(sum)", show(c, d))
c, s, _ = eds("POST", f"/api/v1/documents/{d['id']}/submit", tok["manager"], {})
print("submit", show(c, s))
# автор не может решать свою записку
c, my, _ = eds("GET", "/api/v1/approvals?mine=1", tok["manager"])
print("автор: approvals mine =", c, len(my.get("items", [])))
c, dl, _ = eds("GET", "/api/v1/approvals?mine=1", tok["director"])
ap = [a for a in dl["items"] if a["object"].get("document_id") == d["id"] or a["object"].get("number") == d["number"]]
print("директор: в очереди", [(a["id"], a["title"], a["status"]) for a in ap])
aid = ap[0]["id"]
c, a, _ = eds("GET", f"/api/v1/approvals/{aid}", tok["director"])
print("маршрут до решений:", steps(a), "can_decide:", a["can_decide"])
# бухгалтер раньше директора не может
c, x, _ = eds("POST", f"/api/v1/approvals/{aid}/decision", tok["mgr_acc"], {"decision": "approve"})
print("бухгалтер до директора ->", c, x.get("code") if isinstance(x, dict) else x)
# автор не может
c, x, _ = eds("POST", f"/api/v1/approvals/{aid}/decision", tok["manager"], {"decision": "approve"})
print("автор (нет права шага) ->", c, x.get("code") if isinstance(x, dict) else x)
c, x, _ = eds("POST", f"/api/v1/approvals/{aid}/decision", tok["director"], {"decision": "approve", "comment": "согласовано"})
print("директор approve ->", c, steps(x) if c == 200 else x)
c, acc, _ = eds("GET", "/api/v1/approvals?mine=1", tok["mgr_acc"])
print("бухгалтер: в очереди", [(a["id"] == aid, a["title"]) for a in acc["items"]])
c, x, _ = eds("POST", f"/api/v1/approvals/{aid}/decision", tok["mgr_acc"], {"decision": "approve", "comment": "оплата подтверждена"})
print("бухгалтер approve ->", c, x.get("status") if c == 200 else x, steps(x) if c == 200 else "")
c, dd, _ = eds("GET", f"/api/v1/documents/{d['id']}", tok["manager"])
print("документ после маршрута:", dd.get("number"), dd.get("status"))
st["memo_sum"] = {"id": d["id"], "number": d["number"], "approval": aid}

# --- без суммы
c, d2, _ = eds("POST", "/api/v1/documents", tok["manager"], {"kind": "memo", "subject": "Канцелярия (демо, без суммы)", "text": "Прошу выделить канцтовары."}, headers={"Idempotency-Key": "c1-memo-nosum-1"})
print("create memo(no sum)", show(c, d2))
c, s, _ = eds("POST", f"/api/v1/documents/{d2['id']}/submit", tok["manager"], {})
c, dl, _ = eds("GET", "/api/v1/approvals?mine=1", tok["director"])
ap2 = [a for a in dl["items"] if a["object"].get("number") == d2["number"]]
c, a2, _ = eds("GET", f"/api/v1/approvals/{ap2[0]['id']}", tok["director"])
print("маршрут без суммы:", steps(a2))
c, x, _ = eds("POST", f"/api/v1/approvals/{ap2[0]['id']}/decision", tok["director"], {"decision": "approve"})
print("директор approve ->", c, x.get("status") if c == 200 else x, steps(x) if c == 200 else "")
c, acc, _ = eds("GET", "/api/v1/approvals?mine=1", tok["mgr_acc"])
print("бухгалтер: в очереди по записке без суммы:", [a["title"] for a in acc["items"] if a["object"].get("number") == d2["number"]])
st["memo_nosum"] = {"id": d2["id"], "number": d2["number"], "approval": ap2[0]["id"]}
save(st)

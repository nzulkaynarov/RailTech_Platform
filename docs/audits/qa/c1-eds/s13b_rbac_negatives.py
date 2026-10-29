"""Пункт 6: прямые негативы — тело отказа 403 (код, право)."""
from c1lib import *

st = load()
d, _ = eds_token(crm_token(st, "director"))
c, lst, _ = eds("GET", "/api/v1/letters", d)
lid = [l for l in lst["items"] if l["number"] == "ВХ-001/26"][0]["id"]
T = {k: eds_token(crm_token(st, k))[0] for k in ("mgr_acc", "manager", "admin", "supply")}
cases = [
    ("mgr_acc", "POST", f"/api/v1/letters/{lid}/resolution", {"text": "x", "assignees": [{"crm_user_id": 4, "zone": "goods"}], "due": "2026-12-01"}),
    ("mgr_acc", "POST", "/api/v1/letters", {"subject": "x"}),
    ("manager", "GET", "/api/v1/registry/export", None),
    ("admin", "GET", "/api/v1/registry", None),
    ("supply", "GET", "/api/v1/letters", None),
    ("mgr_acc", "GET", "/api/v1/registry?number=%D0%92%D0%A5-001%2F26", None),
]
for who, m, p, b in cases:
    c, r, _ = eds(m, p, T[who], b)
    print(f"{who:8} {m:4} {p.split('?')[0].replace(lid, '{id}'):40} -> {c} {json.dumps(r.get('code') if isinstance(r, dict) else None)} {json.dumps((r.get('details') if isinstance(r, dict) else None), ensure_ascii=False)}")

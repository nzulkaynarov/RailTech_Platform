"""Пункт 5, находка (Q-C1-E3-1 п. 3): КП готово позже срока резолюции -> одобрить нельзя; выход — новая резолюция? (письмо уже resolved)."""
from c1lib import *

st = load()
dt, _ = eds_token(crm_token(st, "director"))
c, lst, _ = eds("GET", "/api/v1/letters", dt)
late = [l for l in lst["items"] if l["number"] == "ВХ-003/26"][0]
c, r, _ = eds("POST", f"/api/v1/letters/{late['id']}/resolution", dt, {"text": "Продлеваю срок", "assignees": [{"crm_user_id": st["users"]["supply"]["id"], "zone": "goods"}, {"crm_user_id": st["users"]["engineer"]["id"], "zone": "services"}], "due": "2026-12-01", "min_margin_pct": "15.00"})
print("повторная резолюция по resolved-письму ->", c, json.dumps(r, ensure_ascii=False)[:300])

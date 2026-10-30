"""Пункты 2-3: токен директора для EDS (CRM SSO aud=eds -> EDS exchange), список писем, резолюция."""
import datetime
import sys
from c1lib import *

MARGIN = sys.argv[1] if len(sys.argv) > 1 else "15.00"   # порог маржи резолюции, %
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 7       # срок расчёта: сегодня + DAYS (отрицательное — в прошлом)

st = load()
dcrm = crm_token(st, "director")
c, b, _ = req("POST", CRM + "/api/v1/auth/sso/token", {"aud": "eds"}, token=dcrm)
print("CRM sso/token aud=eds:", c, "claims aud/exp:", end=" ")
import base64
pl = json.loads(base64.urlsafe_b64decode(b["token"].split(".")[1] + "=="))
print({k: pl[k] for k in ("iss", "aud", "sub", "permissions") if k in pl}, "ttl", pl["exp"] - pl["iat"])
dt, info = eds_token(dcrm)
print("EDS exchange:", bool(dt), info)
c, me, _ = eds("GET", "/api/v1/me", dt)
print("/me", c, json.dumps(me, ensure_ascii=False))
c, lst, _ = eds("GET", "/api/v1/letters", dt)
print("letters", c, [(l["number"], l["status"]) for l in lst.get("items", lst)] if isinstance(lst, dict) else lst)
items = lst.get("items", [])
letter = [l for l in items if l["status"] == "awaiting_resolution"][-1]  # последнее письмо, ждущее резолюции
due = (datetime.date.today() + datetime.timedelta(days=DAYS)).isoformat()
body = {"text": f"Рассчитать КП: товары — снабжение, услуги — главный инженер. Маржа не ниже {MARGIN} %.",
        "assignees": [{"crm_user_id": st["users"]["supply"]["id"], "zone": "goods"}, {"crm_user_id": st["users"]["engineer"]["id"], "zone": "services"}],
        "due": due, "min_margin_pct": MARGIN}
t0 = time.time()
c, r, _ = eds("POST", f"/api/v1/letters/{letter['id']}/resolution", dt, body)
print("resolution", c, json.dumps(r, ensure_ascii=False)[:700])
st["letter"] = {"id": letter["id"], "number": letter["number"], "t_resolution": t0, "due": due}
save(st)

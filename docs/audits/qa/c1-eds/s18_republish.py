"""C1-G-3: вход сотрудника в EDS (обмен SSO-токена). Аргумент: метка шага. Печатает статус обмена и /me."""
import sys
from c1lib import *

st = load()
key = sys.argv[2] if len(sys.argv) > 2 else "manager"
c0, b0, _ = req("POST", CRM + "/api/v1/auth/sso/token", {"aud": "eds"}, token=crm_token(st, key))
c, b, _ = req("POST", EDS + "/api/v1/auth/sso/exchange", {"token": b0["token"]})
print(sys.argv[1], "| CRM sso/token", c0, "| EDS exchange", c, (b.get("code"), b.get("details")) if c != 200 else "ok")
if c == 200:
    c2, me, _ = eds("GET", "/api/v1/me", b["access_token"])
    print("   /me", c2, sorted(me.get("permissions", [])))

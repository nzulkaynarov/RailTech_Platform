"""Пункт 1 гейта C1: первый запуск — CRM setup, администратор. Код первого запуска передаётся аргументом (берётся из журнала crm-api)."""
import sys
from c1lib import *

code = sys.argv[1]
st = load()
st.setdefault("users", {})
pw = newpw()
c, b, _ = req("GET", CRM + "/api/v1/setup/state")
print("setup/state", c, b)
c, b, _ = req("POST", CRM + "/api/v1/setup/admin", {"code": code, "email": "admin@demo.example", "full_name": "Администратор Демо", "password": pw})
print("setup/admin", c, {k: v for k, v in (b or {}).items() if k != "access_token"} if isinstance(b, dict) else b)
if c == 200:
    st["users"]["admin"] = {"email": "admin@demo.example", "password": pw}
    save(st)

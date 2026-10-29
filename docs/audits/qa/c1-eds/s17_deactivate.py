"""Дополнительно: отключение сотрудника в CRM -> identity.user.deactivated -> уже выданный токен доступа EDS перестаёт работать; возврат доступа."""
from c1lib import *

st = load()
a = crm_token(st, "admin")
uid = st["users"]["engineer"]["id"]
tk, _ = eds_token(crm_token(st, "engineer"))
c, b, _ = eds("GET", "/api/v1/me", tk)
print("до отключения /me ->", c)
t0 = time.time()
c, b, _ = req("PATCH", CRM + f"/api/v1/users/{uid}", {"is_active": False}, token=a)
print("CRM is_active=false ->", c)
res = None
for i in range(60):
    c, b, _ = eds("GET", "/api/v1/me", tk)
    if c != 200:
        res = (c, b.get("code") if isinstance(b, dict) else b, round(time.time() - t0, 2))
        break
    time.sleep(0.25)
print("после отключения /me ->", res)
c, b, _ = req("POST", CRM + "/api/v1/auth/login", {"email": st["users"]["engineer"]["email"], "password": st["users"]["engineer"]["password"]})
print("вход в CRM отключённого ->", c)
c, b, _ = req("PATCH", CRM + f"/api/v1/users/{uid}", {"is_active": True}, token=a)
print("CRM is_active=true ->", c)
res = None
t0 = time.time()
for i in range(60):
    c, b, _ = eds("GET", "/api/v1/me", tk)
    if c == 200:
        res = (c, round(time.time() - t0, 2))
        break
    time.sleep(0.25)
print("после возврата /me ->", res)

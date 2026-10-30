"""Пункт 1: сотрудники CRM (роли каталога, доступ к ERP, провижининг) — для отчёта; без паролей и токенов."""
from c1lib import *

st = load()
a = crm_token(st, "admin")
c, b, _ = req("GET", CRM + "/api/v1/users", token=a)
for u in b:
    print(u["id"], u["email"], [r["name"] for r in u["platform_role_refs"]], "доступ:", u["platform_access"], "erp_sync:", u["erp_sync"])

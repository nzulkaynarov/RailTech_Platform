"""Пункт 1: сотрудники с ролями из каталога, доступ к ERP, первый вход (смена временного пароля)."""
from c1lib import *

st = load()
a = crm_token(st, "admin")
STAFF = [
    # ключ, имя, e-mail, роли каталога (id из /platform-roles: 2 Директор, 3 Менеджер, 4 Снабженец, 5 Гл. инженер, 6 Бухгалтер)
    ("director", "Директор Демо", "director@demo.example", [2]),
    ("mgr_acc", "Менеджер-Бухгалтер Демо", "mgr-acc@demo.example", [3, 6]),   # «Менеджер и бухгалтер»
    ("supply", "Снабженец Демо", "supply@demo.example", [4]),
    ("engineer", "Инженер Демо", "engineer@demo.example", [5]),
    ("manager", "Менеджер Демо", "manager@demo.example", [3]),                  # автор служебных записок, без права бухгалтера
]
for key, name, email, roles in STAFF:
    if key in st["users"]:
        continue
    c, b, _ = req("POST", CRM + "/api/v1/users", {"email": email, "full_name": name, "platform_role_ids": roles}, token=a)
    print("create", key, c, "" if c == 201 else b)
    if c != 201:
        continue
    u = b["user"]
    tmp = b["temporary_password"]
    pw = newpw()
    c2, b2, _ = req("POST", CRM + "/api/v1/auth/login", {"email": email, "password": tmp})
    c3, b3, _ = req("POST", CRM + "/api/v1/auth/change-password", {"current_password": tmp, "new_password": pw}, token=b2["access_token"])
    print("  first login", c2, "change-password", c3)
    st["users"][key] = {"email": email, "password": pw, "id": u["id"], "roles": roles}
    save(st)
c, b, _ = req("GET", CRM + "/api/v1/users", token=a)
for u in b:
    print(u["id"], u["email"], [r["name"] for r in u["platform_role_refs"]], "access=", u["platform_access"], "erp_roles=", u["erp_role_codes"], "erp_sync=", u["erp_sync"])

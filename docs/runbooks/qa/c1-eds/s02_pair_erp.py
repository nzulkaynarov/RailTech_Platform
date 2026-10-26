"""Пункт 1: «Подключить ERP» (как в гейте B) и мастер своей компании ERP по SSO."""
from c1lib import *

st = load()
a = crm_token(st, "admin")
c, b, _ = req("POST", CRM + "/api/v1/integrations/erp/pair", {"base_url": ERP, "password": st["users"]["admin"]["password"]}, token=a)
print("pair", c, json.dumps(b, ensure_ascii=False)[:600])
c, b, _ = req("GET", CRM + "/api/v1/integrations/erp", token=a)
print("erp status", c, json.dumps(b, ensure_ascii=False)[:600])

e = erp_token(a)
print("erp token:", bool(e))
c, b, _ = req("GET", ERP + "/api/v1/setup/status/", token=e)
print("erp setup/status", c, b)
if c == 200 and b.get("setup_required"):
    c, b, _ = req("POST", ERP + "/api/v1/setup/company/", {"name": "ООО «Демо Рейл Сервис»", "inn": "301234567", "legal_address": "г. Ташкент, ул. Демо, 1", "phone": "+998901112233", "email": "info@demo.example"}, token=e)
    print("erp setup/company", c, b)

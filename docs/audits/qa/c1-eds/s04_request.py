"""Пункт 2: заявка из CRM (лид -> согласие -> «Сделать клиентом» = передача в ERP с заявкой). Аргумент: номер клиента 1..N (для повторов)."""
import sys
from c1lib import *

n = sys.argv[1] if len(sys.argv) > 1 else "1"
st = load()
m = crm_token(st, "manager")
t0 = time.time()
c, b, _ = req("POST", CRM + "/api/v1/leads", {"source": "phone", "name": f"Клиент Демо {n}", "company": f"ООО «Демо Заказчик {n}»", "phone": f"+99890100{int(n):04d}", "email": f"demo{n}@client.example", "need": "Нужна поставка и монтаж рельсовых скреплений, партия 500 комплектов (демо)", "language": "ru"}, token=m)
print("create lead", c, b)
lead = b["id"]
c, b, _ = req("POST", CRM + f"/api/v1/leads/{lead}/actions/record_consent", {"method": "phone", "comment": "демо"}, token=m)
print("consent", c, b)
c, b, _ = req("POST", CRM + f"/api/v1/leads/{lead}/actions/make_customer", {"new_client_name": f"ООО «Демо Заказчик {n}»"}, token=m)
print("make_customer", c, b)
client = b["id"]
for _ in range(60):
    c, b, _ = req("GET", CRM + f"/api/v1/clients/{client}", token=m)
    if b.get("erp_handoff_status") not in ("pending", None):
        break
    time.sleep(1)
print("client handoff:", b.get("erp_handoff_status"), b.get("erp_handoff_error"), "erp_company_id" , b.get("erp_company_id"), f"{time.time()-t0:.1f}s")
st.setdefault("req", {})[n] = {"lead": lead, "client": client, "t0": t0}
save(st)

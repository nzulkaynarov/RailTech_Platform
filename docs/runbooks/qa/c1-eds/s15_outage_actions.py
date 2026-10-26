"""Пункт 7: действия, пока EDS остановлен: CRM (заявка, обычный лид, правка роли сотрудника) и ERP (новое КП -> виза -> quote.ready_for_approval)
работают. Печатает статус и время каждого шага."""
import datetime

from c1lib import *


def ts():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S.%f")[:-3]


st = load()
m = crm_token(st, "manager")
a = crm_token(st, "admin")
out = {}
# 1) здоровье
for name, url in (("CRM /health", CRM + "/health"), ("ERP /health", ERP + "/health"), ("EDS /health", EDS + "/health")):
    c, b, _ = req("GET", url, timeout=5)
    print(ts(), name, c)
# 2) CRM: заявка (лид -> клиент -> передача в ERP -> request.created для EDS)
c, b, _ = req("POST", CRM + "/api/v1/leads", {"source": "phone", "name": "Клиент Демо 4", "company": "ООО «Демо Заказчик 4»", "phone": "+998901000004", "email": "demo4@client.example", "need": "Заявка во время остановки EDS (демо)", "language": "ru"}, token=m)
lead = b["id"]
print(ts(), "CRM создать лид", c, lead)
c, b, _ = req("POST", CRM + f"/api/v1/leads/{lead}/actions/record_consent", {"method": "phone", "comment": "демо"}, token=m)
c, b, _ = req("POST", CRM + f"/api/v1/leads/{lead}/actions/make_customer", {"new_client_name": "ООО «Демо Заказчик 4»"}, token=m)
print(ts(), "CRM сделать клиентом (заявка в ERP)", c, b)
client = b["id"]
for _ in range(30):
    c, b, _ = req("GET", CRM + f"/api/v1/clients/{client}", token=m)
    if b.get("erp_handoff_status") == "done":
        break
    time.sleep(1)
print(ts(), "передача в ERP:", b.get("erp_handoff_status"))
# 3) CRM: обычный лид
c, b, _ = req("POST", CRM + "/api/v1/leads", {"source": "email", "name": "Обычный лид (во время остановки EDS)", "need": "консультация", "email": "lead5@client.example"}, token=m)
print(ts(), "CRM обычный лид", c, b)
# 4) CRM: правка роли сотрудника «Менеджер Демо» (+Бухгалтер) -> identity.user.updated
uid = st["users"]["manager"]["id"]
c, b, _ = req("PATCH", CRM + f"/api/v1/users/{uid}", {"platform_role_ids": [3, 6]}, token=a)
print(ts(), "CRM роли сотрудника Менеджер Демо -> Менеджер+Бухгалтер", c, [r["name"] for r in b.get("platform_role_refs", [])] if isinstance(b, dict) else b)
# 5) ERP: новое КП на сделке 1 -> виза инженера -> quote.ready_for_approval (событие копится)
sup = erp_token(crm_token(st, "supply"))
eng = erp_token(crm_token(st, "engineer"))
H = ERP + "/api/v1/crm/"
c, q, _ = req("POST", H + "quotes/", {"deal": 1}, token=sup)
qid = q["id"]
print(ts(), "ERP новое КП на сделке 1", c, qid)
for it in ({"quote": qid, "imported_raw_name": "Подкладка Д65 (демо)", "quantity": 300, "unit": "шт.", "frozen_base_price": "800.00", "frozen_currency": "UZS", "margin_percent": "30.00"},):
    c, b, _ = req("POST", H + "quote-items/", it, token=sup)
c, b, _ = req("POST", H + f"quotes/{qid}/submit-for-review/", {}, token=sup)
print(ts(), "ERP на согласование", c)
c, q, _ = req("GET", H + f"quotes/{qid}/", token=sup)
step = [s for s in q["approval_steps"] if s.get("status") == "PENDING"][0]["id"]
c, b, _ = req("POST", H + f"quotes/{qid}/approval-act/", {"step_id": step, "decision": "APPROVE", "comment": "виза во время остановки EDS"}, token=eng)
print(ts(), "ERP виза инженера", c, (b.get("number"), b.get("status")) if isinstance(b, dict) else b)
st["outage"] = {"lead_client": client, "quote": qid, "role_user": uid}
save(st)

"""Подготовка к s16: КП №3 (маршрут у директора) как цель отзыва; вывод полей КП в API ERP (C1-G-5)."""
from c1lib import *

st = load()
st["outage"] = {"quote": st["quote3"]["id"]}
save(st)
sup = erp_token(crm_token(st, "supply"))
c, q, _ = req("GET", ERP + "/api/v1/crm/quotes/%d/" % st["quote2"]["id"], token=sup)
print("C1-G-5: поля КП №2 (SENT, ИСХ-002/26) в API ERP, содержащие outgoing/director/send_channels/eds:", [k for k in q if any(s in k for s in ("outgoing", "director", "send_channels", "eds"))] or "нет")

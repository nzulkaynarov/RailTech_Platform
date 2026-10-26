"""Пункт 5: отправка клиенту до одобрения в EDS (КП в PENDING_APPROVAL) — отказ INVALID_STATUS. Аргумент: ключ КП в состоянии."""
import sys
from c1lib import *

st = load()
qid = st[sys.argv[1] if len(sys.argv) > 1 else "quote2"]["id"]
d = erp_token(crm_token(st, "director"))
c, b, _ = req("POST", ERP + f"/api/v1/crm/quotes/{qid}/send-to-client/", {}, token=d)
print("send-to-client до одобрения (PENDING_APPROVAL), от директора:", c, b)

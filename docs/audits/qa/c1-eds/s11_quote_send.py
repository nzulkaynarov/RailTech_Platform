"""Пункт 5 (часть Д): отправка клиенту разблокирована после одобрения в EDS (ИСХ-номер на КП)."""
import sys
from c1lib import *

st = load()
KEY = sys.argv[1] if len(sys.argv) > 1 else "quote"
qid = st[KEY]["id"]
sup = erp_token(crm_token(st, "director"))  # quote.send есть только у ролей с eds.drafts=full (Директор, Администратор)
sup_author = erp_token(crm_token(st, "supply"))
c, b, _ = req("POST", ERP + f"/api/v1/crm/quotes/{qid}/send-to-client/", {}, token=sup_author)
print("send-to-client автором (снабженец):", c, b)
c, b, _ = req("POST", ERP + f"/api/v1/crm/quotes/{qid}/send-to-client/", {}, token=sup)
print("send-to-client:", c, json.dumps(b, ensure_ascii=False)[:400] if c != 200 else (b.get("status_code"), "frozen" if b.get("frozen_at") else ""))

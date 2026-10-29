"""Дополнительно: отказы входа (повтор SSO-токена, чужой aud), отзыв КП автором после передачи директору (Q-C1-E5-1), отклонение письма -> сделка LOST в ERP."""
from c1lib import *

st = load()
m = crm_token(st, "supply")
# а) повтор токена и чужой aud
c, b, _ = req("POST", CRM + "/api/v1/auth/sso/token", {"aud": "eds"}, token=m)
t = b["token"]
c1, b1, _ = req("POST", EDS + "/api/v1/auth/sso/exchange", {"token": t})
c2, b2, _ = req("POST", EDS + "/api/v1/auth/sso/exchange", {"token": t})
print("обмен токена: 1-й", c1, "| повтор того же", c2, b2.get("details") if isinstance(b2, dict) else b2)
c, b, _ = req("POST", CRM + "/api/v1/auth/sso/token", {"aud": "erp"}, token=m)
c3, b3, _ = req("POST", EDS + "/api/v1/auth/sso/exchange", {"token": b["token"]})
print("токен aud=erp в EDS ->", c3, b3.get("details") if isinstance(b3, dict) else b3)
c4, b4, _ = req("POST", EDS + "/api/v1/auth/sso/exchange", {"token": "x.y.z"})
print("мусорный токен ->", c4, b4.get("details") if isinstance(b4, dict) else b4)
c5, b5, _ = req("GET", EDS + "/api/v1/letters")
print("запрос без Bearer ->", c5, b5.get("code") if isinstance(b5, dict) else b5)
# сотрудник без доступа к EDS не получает токен: неактивного проверим в п. 7 отдельно
# б) отзыв КП автором после передачи директору
sup = erp_token(m)
qid = st["outage"]["quote"]
c, b, _ = req("POST", ERP + f"/api/v1/crm/quotes/{qid}/recall/", {}, token=sup)
print("recall КП у директора ->", c, b)
# в) директор отклоняет письмо ВХ-054/26 -> ERP: сделка 4 LOST
dt, _ = eds_token(crm_token(st, "director"))
c, lst, _ = eds("GET", "/api/v1/letters?status=awaiting_resolution", dt)
lt = [l for l in lst["items"] if l["links"].get("erp_deal_id") == 4][0]
t0 = time.time()
c, r, _ = eds("POST", f"/api/v1/letters/{lt['id']}/reject", dt, {"reason": "Не наш профиль (демо)"})
print("reject письма", lt["number"], "->", c, r.get("status") if isinstance(r, dict) else r)
time.sleep(4)
print("прошло", round(time.time() - t0, 1), "с")

"""Пункт 6: резолюция директора по письму. Аргументы: letter_id days margin  (days: сдвиг срока от сегодня, может быть отрицательным)"""
import datetime, sys
from c1lib import *

lid, days, margin = sys.argv[1], int(sys.argv[2]), sys.argv[3]
st = load()
dt, _ = eds_token(crm_token(st, "director"))
due = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
body = {"text": f"Рассчитать КП. Маржа не ниже {margin} %.",
        "assignees": [{"crm_user_id": st["users"]["supply"]["id"], "zone": "goods"}, {"crm_user_id": st["users"]["engineer"]["id"], "zone": "services"}],
        "due": due, "min_margin_pct": margin}
c, r, _ = eds("POST", f"/api/v1/letters/{lid}/resolution", dt, body)
print(f"резолюция due={due} (сдвиг {days:+d} дн.), порог {margin} % ->", c, json.dumps(r, ensure_ascii=False)[:400])

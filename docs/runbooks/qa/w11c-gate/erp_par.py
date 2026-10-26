"""Параллельные публикации ERP: K потоков по барьеру, каждый — одна транзакция с событием deal.stage_changed.
docker exec -i -e GEN_K=25 rt-w11c-erp-backend-1 python manage.py shell < erp_par.py"""
import os, threading, time
from django.db import connection, transaction
from sales.models import Deal
from integration.services import events

K = int(os.environ.get("GEN_K", "25"))
deal = Deal.objects.exclude(company__isnull=True).order_by("id").first()
bar = threading.Barrier(K)
res = []

def work(i):
    try:
        bar.wait()
        t0 = time.time()
        with transaction.atomic():
            ev = events.publish_deal_stage_changed(deal, "request", "quoting", reason=f"par {i}")
        res.append((bool(ev), time.time() - t0))
    except Exception as e:  # noqa
        res.append((repr(e)[:80], 0))
    finally:
        connection.close()

th = [threading.Thread(target=work, args=(i,)) for i in range(K)]
[t.start() for t in th]; [t.join() for t in th]
ok = sum(1 for r in res if r[0] is True)
print("erp_par: опубликовано", ok, "из", K, "ошибки:", [r[0] for r in res if r[0] is not True][:3], "max_s=%.2f" % max(r[1] for r in res))

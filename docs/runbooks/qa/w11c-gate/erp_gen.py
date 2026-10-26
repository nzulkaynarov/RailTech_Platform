"""Генератор событий ERP: request.created по существующей сделке (те же сервисы продукта, один коммит на событие).
Запуск: docker exec -i -e GEN_N=.. -e GEN_SLEEP=.. rt-w11c-erp-backend-1 python manage.py shell < erp_gen.py"""
import os, random, time
from django.db import transaction
from sales.models import Deal
from integration.services import events

N = int(os.environ.get("GEN_N", "10"))
SLEEP = float(os.environ.get("GEN_SLEEP", "1.0"))
KIND = os.environ.get("GEN_KIND", "stage")
JIT = os.environ.get("GEN_JITTER", "1") == "1"
deal = Deal.objects.exclude(company__isnull=True).order_by("id").first()
ok = 0
for i in range(N):
    with transaction.atomic():
        ev = events.publish_deal_stage_changed(deal, "request", "quoting", reason=f"gate load {i}") if KIND == "stage" else events.publish_request_created(deal, source="erp", summary=f"gate load {i}")
    ok += 1 if ev else 0
    time.sleep(random.uniform(0, SLEEP * 2) if JIT else SLEEP)
print("erp published", ok, "of", N)

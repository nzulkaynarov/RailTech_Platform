"""Синтетика для пункта 6: событие quote.ready_for_approval без визы гл. инженера (в реальном потоке ERP открывает маршрут только после всех виз).
Берёт КП-2026-00002 (возвращённое), строит payload штатной функцией, убирает визу зоны services и поднимает маржу в снимке выше порога —
в чек-листе остаётся одна красная блокирующая строка (виза), остальное — штатные сервисы публикации."""
from django.db import transaction
from django.utils import timezone
from crm.models import Quote
from crm.services import eds_quote_approval as eqa
from integration.services import events

q = Quote.objects.select_related("deal", "deal__company").get(number="КП-2026-00002")
with transaction.atomic():
    q.eds_revision += 1
    q.save(update_fields=["eds_revision"])
    payload = eqa.build_ready_payload(q, ready_at=timezone.now())
    payload["visas"] = [v for v in payload["visas"] if v["zone"] != "services"]
    payload["margin_pct"] = "30.00"
    events.publish_quote_ready_for_approval(q, payload, actor={"type": "system"})
print("опубликовано: ревизия", q.eds_revision, "визы:", [v["zone"] for v in payload["visas"]], "required_zones:", payload["required_zones"])

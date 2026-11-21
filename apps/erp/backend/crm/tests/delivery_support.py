"""СЦ-9: акт выпускается после доставки — тесты, которым акт нужен как данность, сначала «доставляют» сделку."""

from crm.models import Fulfillment, FulfillmentStatus


def mark_delivered(deal, code: str = "DELIVERED") -> Fulfillment:
    """Исполнение сделки в статусе `code` (по умолчанию «Доставлено»): создаёт или обновляет."""
    status, _ = FulfillmentStatus.objects.get_or_create(code=code, defaults={"name": code, "sort_order": 10})
    fulfillment, _ = Fulfillment.objects.update_or_create(deal=deal, defaults={"status": status})
    return fulfillment

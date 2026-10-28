"""Задачи снабжения (D2-2): ежедневное уведомление о просроченных заказах поставщикам."""

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="supply.notify_overdue_orders", time_limit=300, soft_time_limit=240)
def notify_overdue_orders() -> dict:
    """Ожидаемая дата заказа прошла, заказ не получен → уведомление `supplier_order.overdue` создателю и держателям права
    снабжения (раз на заказ; новая ожидаемая дата или подтверждение снимают отметку — о новой просрочке скажем снова).
    """
    from supply.services.orders import notify_overdue

    sent = notify_overdue()
    logger.info("supply.notify_overdue_orders: отправлено %s уведомлений", sent)
    return {"sent": sent}

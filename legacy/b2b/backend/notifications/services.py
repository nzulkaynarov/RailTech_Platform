"""
Notification business logic — single source of truth.

Called from both Django Unfold actions and DRF endpoints.
See ADR-0001 and CLAUDE.md IRON RULE 8.
"""

import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db.models import QuerySet

from .models import Notification

logger = logging.getLogger(__name__)


def mark_notifications_read(notifications: QuerySet[Notification]) -> int:
    """
    Mark a queryset of notifications as read.

    Returns: count of notifications updated (only previously-unread ones).
    """
    return notifications.filter(is_read=False).update(is_read=True)


def notify_platform_admins(
    title: str,
    message: str,
    link: str = "",
    type_code: str = "WARNING",
    event_code: str = "",
    event_params: dict | None = None,
) -> Notification:
    """
    Создаёт broadcast-уведомление для всех Platform Admin (audience=PLATFORM_ADMIN, user=NULL).

    Используется для операционных алёртов платформы: failed payments, expired subscriptions,
    stuck Celery tasks, KYC queue growing и т.п. Обычные пользователи этот канал НЕ видят.
    """
    from .models import NotificationType

    ntype = NotificationType.objects.filter(code=type_code).first()
    notification = Notification.objects.create(
        audience=Notification.AUDIENCE_PLATFORM_ADMIN,
        user=None,
        type=ntype,
        title=title,
        message=message,
        link=link,
        event_code=event_code,
        event_params=event_params or {},
    )
    return notification


def spa_link(page: str, object_id=None) -> str:
    """Точная ссылка на ОБЪЕКТ внутри SPA — хэш-маршрут с ведущим «#».

    Соглашение с фронтендом: ссылка, начинающаяся с «#», — готовый маршрут SPA, и центр
    уведомлений открывает именно его. Ссылки без «#» остаются легаси-путями вида `/crm/deals`
    и обрабатываются по-прежнему, поэтому старые уведомления не ломаются.

    Нужно затем, что «уведомление ведёт на объект» иначе невыразимо: у модели уведомления
    есть только FK на сделку, и любое событие по счёту, акту или отгрузке приводило человека
    на карточку сделки вообще, а не к документу, о котором его известили.
    """
    return f"#{page}?open={object_id}" if object_id else f"#{page}"


def notify_user(
    *,
    user,
    title: str,
    message: str,
    link: str = "",
    deal=None,
    type_code: str = "INFO",
    push: bool = True,
    event_code: str = "",
    event_params: dict | None = None,
) -> Notification | None:
    """Создать уведомление пользователю и (по умолчанию) сразу доставить его по WebSocket.

    Возвращает None, если получателя нет: у сделок сплошь и рядом пустой legacy-`manager`,
    и вызывающему удобнее получить None, чем городить проверку на каждой площадке.

    L1: `event_code` + `event_params` — машинная пара, по которой клиент собирает текст на
    языке ЗРИТЕЛЯ. `title`/`message` при этом обязательны: они остаются RU-fallback для
    Unfold-админки и для строк, записанных до появления кода.
    """
    from .models import NotificationType

    if user is None:
        return None
    notification = Notification.objects.create(
        user=user,
        type=NotificationType.objects.filter(code=type_code).first(),
        title=title,
        message=message,
        link=link,
        deal=deal,
        event_code=event_code,
        event_params=event_params or {},
    )
    if push:
        push_notification_ws(notification)
    return notification


def push_notification_ws(notification: Notification):
    """Push a notification to the user via WebSocket channel layer."""
    if not notification.user_id:
        return
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"notifications_{notification.user_id}",
            {
                "type": "notification.push",
                "data": {
                    "id": notification.id,
                    "title": notification.title,
                    "message": notification.message,
                    # L1: живое WS-уведомление обязано нести ту же машинную пару, что и
                    # ответ API, иначе оно приходило бы по-русски, а после перезагрузки
                    # страницы то же событие внезапно печаталось на языке зрителя.
                    "event_code": notification.event_code or "",
                    "event_params": notification.event_params or {},
                    "link": notification.link or "",
                    # Без `deal` живое WS-уведомление приходило на фронт «безадресным» и
                    # уводило в общий список — правильная ссылка появлялась только после
                    # перезагрузки страницы, когда список тянулся из API.
                    "deal": notification.deal_id,
                    "type": notification.type.code if notification.type else "INFO",
                    "is_read": notification.is_read,
                    "created_at": notification.created_at.isoformat() if notification.created_at else "",
                },
            },
        )
    except Exception:  # noqa: BLE001 — fault barrier: best-effort WS push must never break the caller
        logger.exception("Failed to push WebSocket notification %s", notification.pk)

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
    )
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
                    "link": notification.link or "",
                    "type": notification.type.code if notification.type else "INFO",
                    "is_read": notification.is_read,
                    "created_at": notification.created_at.isoformat() if notification.created_at else "",
                },
            },
        )
    except Exception:
        logger.exception("Failed to push WebSocket notification %s", notification.pk)

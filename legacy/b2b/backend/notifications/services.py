"""
Notification business logic — single source of truth.

Called from both Django Unfold actions and DRF endpoints.
See ADR-0001 and CLAUDE.md IRON RULE 8.
"""
from django.db.models import QuerySet

from .models import Notification


def mark_notifications_read(notifications: QuerySet[Notification]) -> int:
    """
    Mark a queryset of notifications as read.

    Returns: count of notifications updated (only previously-unread ones).
    """
    return notifications.filter(is_read=False).update(is_read=True)

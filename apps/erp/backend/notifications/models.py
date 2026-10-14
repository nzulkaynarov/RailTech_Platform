"""Notifications models — consolidated into core per ADR-0006.

Re-exported here for backward compatibility.
"""

from core.models import EmailLog, EmailTemplate, Notification, NotificationType

__all__ = [
    "EmailLog",
    "EmailTemplate",
    "Notification",
    "NotificationType",
]

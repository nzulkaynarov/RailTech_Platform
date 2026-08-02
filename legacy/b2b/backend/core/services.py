"""
Core business logic — SupportTicket workflow.

Per IRON RULE 8, all business logic (status transitions, notifications,
side effects) lives here. Views and admin actions are thin wrappers.
"""

from django.utils import timezone

from core.models import SupportTicket, SupportTicketMessage
from notifications.services import notify_platform_admins


def create_support_ticket(
    *,
    author,
    subject: str,
    description: str,
    category: str = SupportTicket.CATEGORY_QUESTION,
    priority: str = SupportTicket.PRIORITY_NORMAL,
) -> SupportTicket:
    """
    Создаёт тикет от лица пользователя.

    Автоматически:
    - связывает тикет с primary_company автора (если есть);
    - уведомляет Platform Admin через broadcast-канал.
    """
    company = getattr(author, "primary_company", None)
    ticket = SupportTicket.objects.create(
        subject=subject,
        description=description,
        category=category,
        priority=priority,
        created_by=author,
        company=company,
    )
    # Раньше сюда клали i18n-КЛЮЧИ как текст («support.alert.new_ticket_title»), а
    # NotificationCenter их не переводит и самих ключей в локалях не было — оператор видел
    # на экране буквально точечную строку. Теперь как у всех: RU-fallback + машинный код.
    notify_platform_admins(
        title="Новый тикет поддержки",
        message=f"Тикет #{ticket.pk}: {ticket.subject}",
        link=f"/admin/support/{ticket.pk}",
        type_code="INFO",
        event_code="support.ticket_created",
        event_params={"ticket_id": ticket.pk, "subject": ticket.subject},
    )
    return ticket


def add_ticket_message(
    *,
    ticket: SupportTicket,
    author,
    text: str,
    is_internal: bool = False,
) -> SupportTicketMessage:
    """
    Добавляет сообщение в тикет.

    - is_internal=True доступно только Platform Admin (проверяется в view).
    - автоматически переводит OPEN-тикет в IN_PROGRESS при ответе админа.
    """
    message = SupportTicketMessage.objects.create(
        ticket=ticket,
        author=author,
        text=text,
        is_internal=is_internal,
    )
    if author and author.is_platform_admin and ticket.status == SupportTicket.STATUS_OPEN and not is_internal:
        ticket.status = SupportTicket.STATUS_IN_PROGRESS
        ticket.save(update_fields=["status", "updated_at"])
    return message


def change_ticket_status(*, ticket: SupportTicket, status: str, actor) -> SupportTicket:
    """Смена статуса тикета Platform Admin'ом.

    `actor` принимался и НИКУДА не записывался: кто закрыл обращение, нигде не фиксировалось,
    хотя вьюха исправно передавала пользователя, а соседний сервис заявок на роль пишет
    `log_admin_action` на каждое решение. Параметр, который ничего не делает, обещает аудит,
    которого нет, — поэтому он теперь действительно ведёт запись.
    """
    from core.audit import log_admin_action

    valid = {code for code, _ in SupportTicket.STATUS_CHOICES}
    if status not in valid:
        return None
    before_status = ticket.status
    ticket.status = status
    if status == SupportTicket.STATUS_RESOLVED and not ticket.resolved_at:
        ticket.resolved_at = timezone.now()
    ticket.save(update_fields=["status", "resolved_at", "updated_at"])
    log_admin_action(
        entity_type="support_ticket",
        entity_id=ticket.id,
        action="Изменён статус обращения",
        detail=f"{before_status} → {status}",
        event_code="support.ticket_status_changed",
        event_params={"from": before_status, "to": status},
        actor=actor,
        before={"status": before_status},
        after={"status": status},
    )
    return ticket


def assign_ticket(*, ticket: SupportTicket, assignee) -> SupportTicket:
    """Назначить Platform Admin на тикет."""
    ticket.assigned_to = assignee
    if ticket.status == SupportTicket.STATUS_OPEN:
        ticket.status = SupportTicket.STATUS_IN_PROGRESS
    ticket.save(update_fields=["assigned_to", "status", "updated_at"])
    return ticket

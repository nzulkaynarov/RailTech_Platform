"""Рабочий процесс тикетов поддержки (`core.services`).

Модуль был покрыт на 24%. Логика небольшая, но в ней есть неочевидные правила, которые
легко потерять при правке: внутренняя заметка администратора НЕ считается ответом клиенту и
не двигает тикет в работу; назначение исполнителя не должно откатывать уже решённый тикет;
неизвестный статус возвращается как None, и на этом держится ошибка `SUPPORT_INVALID_STATUS`
во вьюхе.
"""

from unittest.mock import patch

import pytest

from accounts.models import Company, CompanyMember, CompanyType, CustomUser, SystemRole, WorkspaceRole
from core.models import SupportTicket, SupportTicketMessage
from core.services import add_ticket_message, assign_ticket, change_ticket_status, create_support_ticket


@pytest.fixture
def world(db):
    WorkspaceRole.objects.get_or_create(code="OWNER", defaults={"name": "Owner", "sort_order": 10})
    CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент", "sort_order": 10})
    admin_role = SystemRole.objects.get_or_create(code="ADMIN", defaults={"name": "Admin", "sort_order": 10})[0]

    company = Company.objects.create(name="Компания автора", inn="8000000008")
    company.types.add(CompanyType.objects.get(code="CLIENT"))
    author = CustomUser.objects.create_user(email="author@support.test", username="support_author", password="pw")
    CompanyMember.objects.create(
        user=author,
        company=company,
        role=WorkspaceRole.objects.get(code="OWNER"),
        is_active=True,
        is_primary=True,
    )
    operator = CustomUser.objects.create_user(
        is_superuser=True, email="operator@support.test", username="support_operator", password="pw", role=admin_role
    )
    return {"company": company, "author": author, "operator": operator}


def _ticket(world, status=SupportTicket.STATUS_OPEN) -> SupportTicket:
    return SupportTicket.objects.create(
        subject="Не открывается КП",
        description="Кнопка не реагирует",
        category=SupportTicket.CATEGORY_BUG,
        priority=SupportTicket.PRIORITY_NORMAL,
        created_by=world["author"],
        company=world["company"],
        status=status,
    )


@pytest.mark.django_db
class TestCreateSupportTicket:
    def test_ticket_is_linked_to_the_authors_primary_company(self, world):
        """Компания подставляется сама — оператор должен видеть, от кого обращение."""
        with patch("core.services.notify_platform_admins"):
            ticket = create_support_ticket(author=world["author"], subject="Тема", description="Текст")
        assert ticket.company == world["company"]
        assert ticket.created_by == world["author"]
        assert ticket.status == SupportTicket.STATUS_OPEN

    def test_author_without_company_still_gets_a_ticket(self, world):
        """Пользователь без компании (например, до завершения профиля) не должен упираться в 500."""
        loner = CustomUser.objects.create_user(email="loner@support.test", username="support_loner", password="pw")
        with patch("core.services.notify_platform_admins"):
            ticket = create_support_ticket(author=loner, subject="Тема", description="Текст")
        assert ticket.company is None

    def test_defaults_are_question_and_normal(self, world):
        with patch("core.services.notify_platform_admins"):
            ticket = create_support_ticket(author=world["author"], subject="Тема", description="Текст")
        assert ticket.category == SupportTicket.CATEGORY_QUESTION
        assert ticket.priority == SupportTicket.PRIORITY_NORMAL

    def test_platform_admins_are_notified_with_a_deep_link(self, world):
        """Уведомление ведёт на конкретный тикет — иначе оператору некуда нажать."""
        with patch("core.services.notify_platform_admins") as notify:
            ticket = create_support_ticket(author=world["author"], subject="Тема", description="Текст")
        notify.assert_called_once()
        assert notify.call_args.kwargs["link"] == f"/admin/support/{ticket.pk}"


@pytest.mark.django_db
class TestAddTicketMessage:
    def test_admin_reply_moves_open_ticket_into_progress(self, world):
        ticket = _ticket(world)
        add_ticket_message(ticket=ticket, author=world["operator"], text="Смотрим")
        ticket.refresh_from_db()
        assert ticket.status == SupportTicket.STATUS_IN_PROGRESS

    def test_internal_note_does_not_move_the_ticket(self, world):
        """КЛЮЧЕВОЕ правило: внутренняя заметка — не ответ клиенту. Тикет остаётся открытым,
        иначе обращение выглядит взятым в работу, хотя пользователю никто не написал."""
        ticket = _ticket(world)
        add_ticket_message(ticket=ticket, author=world["operator"], text="Похоже на дубль", is_internal=True)
        ticket.refresh_from_db()
        assert ticket.status == SupportTicket.STATUS_OPEN

    def test_author_reply_does_not_move_the_ticket(self, world):
        """Сообщение самого пользователя не переводит тикет в работу — это делает оператор."""
        ticket = _ticket(world)
        add_ticket_message(ticket=ticket, author=world["author"], text="Ещё подробности")
        ticket.refresh_from_db()
        assert ticket.status == SupportTicket.STATUS_OPEN

    def test_resolved_ticket_is_not_reopened_by_an_admin_reply(self, world):
        """Переход только из OPEN: ответ в решённом тикете не тянет его обратно в работу."""
        ticket = _ticket(world, status=SupportTicket.STATUS_RESOLVED)
        add_ticket_message(ticket=ticket, author=world["operator"], text="Дополню")
        ticket.refresh_from_db()
        assert ticket.status == SupportTicket.STATUS_RESOLVED

    def test_message_is_stored_with_its_flags(self, world):
        ticket = _ticket(world)
        message = add_ticket_message(ticket=ticket, author=world["operator"], text="Заметка", is_internal=True)
        assert isinstance(message, SupportTicketMessage)
        assert (message.ticket, message.author, message.is_internal) == (ticket, world["operator"], True)


@pytest.mark.django_db
class TestChangeTicketStatus:
    def test_unknown_status_returns_none_and_changes_nothing(self, world):
        """На этом None держится ошибка SUPPORT_INVALID_STATUS во вьюхе."""
        ticket = _ticket(world)
        assert change_ticket_status(ticket=ticket, status="НЕТ_ТАКОГО", actor=world["operator"]) is None
        ticket.refresh_from_db()
        assert ticket.status == SupportTicket.STATUS_OPEN

    @pytest.mark.parametrize("status", ["OPEN", "IN_PROGRESS", "RESOLVED", "CLOSED"])
    def test_every_declared_status_is_accepted(self, world, status):
        ticket = _ticket(world)
        updated = change_ticket_status(ticket=ticket, status=status, actor=world["operator"])
        assert updated is not None
        ticket.refresh_from_db()
        assert ticket.status == status

    def test_status_change_is_audited_with_the_actor(self, world):
        """`actor` принимался и никуда не записывался: кто закрыл обращение, нигде не
        фиксировалось, хотя соседний сервис заявок на роль пишет запись на каждое решение."""
        from crm.models import ActivityLog

        ticket = _ticket(world)
        change_ticket_status(ticket=ticket, status=SupportTicket.STATUS_RESOLVED, actor=world["operator"])

        entry = ActivityLog.objects.filter(event_code="support.ticket_status_changed").first()
        assert entry is not None, "смена статуса обращения не попала в аудит"
        assert entry.user_id == world["operator"].id, "в аудите не тот, кто менял статус"
        assert entry.event_params == {"from": SupportTicket.STATUS_OPEN, "to": SupportTicket.STATUS_RESOLVED}

    def test_rejected_status_is_not_audited(self, world):
        """Неизвестный статус ничего не меняет — значит и записывать нечего."""
        from crm.models import ActivityLog

        ticket = _ticket(world)
        change_ticket_status(ticket=ticket, status="НЕТ_ТАКОГО", actor=world["operator"])

        assert not ActivityLog.objects.filter(event_code="support.ticket_status_changed").exists()

    def test_resolving_stamps_the_resolution_time(self, world):
        ticket = _ticket(world)
        change_ticket_status(ticket=ticket, status=SupportTicket.STATUS_RESOLVED, actor=world["operator"])
        ticket.refresh_from_db()
        assert ticket.resolved_at is not None

    def test_re_resolving_keeps_the_original_time(self, world):
        """Момент решения — это когда решили ВПЕРВЫЕ; повторное проставление его бы затёрло."""
        ticket = _ticket(world)
        change_ticket_status(ticket=ticket, status=SupportTicket.STATUS_RESOLVED, actor=world["operator"])
        ticket.refresh_from_db()
        first_resolved_at = ticket.resolved_at

        change_ticket_status(ticket=ticket, status=SupportTicket.STATUS_IN_PROGRESS, actor=world["operator"])
        change_ticket_status(ticket=ticket, status=SupportTicket.STATUS_RESOLVED, actor=world["operator"])
        ticket.refresh_from_db()
        assert ticket.resolved_at == first_resolved_at

    def test_closing_does_not_stamp_resolution_time(self, world):
        """Закрыт ≠ решён: закрытие без решения не должно проставлять момент решения."""
        ticket = _ticket(world)
        change_ticket_status(ticket=ticket, status=SupportTicket.STATUS_CLOSED, actor=world["operator"])
        ticket.refresh_from_db()
        assert ticket.resolved_at is None


@pytest.mark.django_db
class TestAssignTicket:
    def test_assigning_takes_an_open_ticket_into_progress(self, world):
        ticket = _ticket(world)
        assign_ticket(ticket=ticket, assignee=world["operator"])
        ticket.refresh_from_db()
        assert ticket.assigned_to == world["operator"]
        assert ticket.status == SupportTicket.STATUS_IN_PROGRESS

    def test_assigning_does_not_reopen_a_resolved_ticket(self, world):
        """Назначение исполнителя не должно откатывать статус решённого тикета."""
        ticket = _ticket(world, status=SupportTicket.STATUS_RESOLVED)
        assign_ticket(ticket=ticket, assignee=world["operator"])
        ticket.refresh_from_db()
        assert ticket.status == SupportTicket.STATUS_RESOLVED
        assert ticket.assigned_to == world["operator"]

    def test_unassigning_is_possible(self, world):
        """Снятие исполнителя — валидная операция (передача тикета обратно в общую очередь)."""
        ticket = _ticket(world, status=SupportTicket.STATUS_IN_PROGRESS)
        assign_ticket(ticket=ticket, assignee=world["operator"])
        assign_ticket(ticket=ticket, assignee=None)
        ticket.refresh_from_db()
        assert ticket.assigned_to is None

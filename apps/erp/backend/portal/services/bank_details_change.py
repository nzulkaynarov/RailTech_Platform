"""Смена банковских реквизитов компании из кабинета (FX-4; решение владельца 2026-11-08).

Администратор подаёт запрос — реквизиты не меняются; сотрудник (право `finance.payment`) подтверждает или отклоняет с причиной.
Подтвердить изменённые реквизиты или реквизиты архивной компании нельзя (`BANK_CHANGE_STALE`, `COMPANY_ARCHIVED`).

Паттерн — Maker-checker (SAP «чувствительные поля» и подтверждение FK08, Odoo `account.group_validate_bank_account`): один
активный запрос на компанию, чтобы сотрудник не подтвердил другой счёт, чем сверял. Новая смена при активном запросе —
`BANK_CHANGE_ALREADY_PENDING`, а не замена.

Подача и решение блокируют строку компании (`select_for_update`) — две подачи и два подтверждения идут по очереди; повтор
решения в том же смысле не даёт второго эффекта. Уведомления — группа `security` (`portal/services/notices.py`): администраторы и
основной контакт по всем каналам. В журнал и уведомления полный номер счёта не пишем (`mask_bank_details`).
"""

from __future__ import annotations

import re
from typing import Optional

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from parties.models import Company, Contact, active_contact_q

from ..exceptions import PortalConflict
from ..models import (
    BankDetailsChangeRequest,
    BankDetailsChangeStatus,
    PortalSecurityEvent,
    record_portal_security_event,
)
from . import notices

ALREADY_PENDING = "BANK_CHANGE_ALREADY_PENDING"
NOT_PENDING = "BANK_CHANGE_NOT_PENDING"
STALE = "BANK_CHANGE_STALE"
ARCHIVED = "COMPANY_ARCHIVED"

KIND_REQUESTED = "bank_requisites_change_requested"
KIND_APPROVED = "bank_requisites_changed"
KIND_REJECTED = "bank_requisites_change_rejected"

#: Имя в журнале кабинета вместо имени сотрудника: клиенту не раскрываем, кто именно решил.
STAFF_ACTOR = "Сотрудник"

_DIGITS = re.compile(r"\d[\d \-]{3,}\d")


def mask_bank_details(text: str) -> str:
    """Самый длинный ряд цифр — последние 4 знака: `•••• 7777`. Цифр нет — пусто."""
    runs = [re.sub(r"\D", "", match) for match in _DIGITS.findall(text or "")]
    if not runs:
        return ""
    return f"•••• {max(runs, key=len)[-4:]}"


def _lock_company(company_id: int) -> Company:
    return Company.objects.select_for_update().get(pk=company_id)


def notify_change(company: Company, *, kind: str, request_id: int, params: Optional[dict] = None) -> list:
    """Уведомление всем администраторам и основному контакту компании. Ключ — запрос и вид: отдельная смена не теряется, повтор той же доставки не дублируется."""
    contact_ids = list(
        Contact.objects.filter(active_contact_q(), Q(is_admin=True) | Q(is_primary=True), company=company).values_list(
            "pk", flat=True
        )
    )
    return notices.notify(
        kind,
        company=company,
        object_id=request_id,
        params=params or {},
        link="/company",
        dedup=f"bank_change:{request_id}",
        document_contact_ids=contact_ids,
        contact_ids=contact_ids,
    )


def submit(company: Company, contact: Contact, new_value: str, *, ip: str, user_agent: str) -> BankDetailsChangeRequest:
    """Подать запрос: старые реквизиты действуют до решения сотрудника."""
    with transaction.atomic():
        locked = _lock_company(company.pk)
        if BankDetailsChangeRequest.objects.filter(
            company_id=company.pk, status=BankDetailsChangeStatus.PENDING
        ).exists():
            raise PortalConflict(ALREADY_PENDING)
        request = BankDetailsChangeRequest.objects.create(
            company=locked,
            old_bank_details=locked.formatted_bank_details or "",
            new_bank_details=new_value,
            requested_by_contact=contact,
            requested_by_name=contact.name or contact.email,
            requested_by_email=contact.email or "",
            requested_ip=ip or None,
            user_agent=user_agent or "",
        )
        record_portal_security_event(
            locked,
            PortalSecurityEvent.EventType.BANK_DETAILS_CHANGE_REQUESTED,
            actor_contact=contact,
            ip_address=ip or None,
            user_agent=user_agent,
            details=f"Запрошена смена реквизитов, счёт {mask_bank_details(new_value) or '—'}",
        )
        notify_change(
            locked, kind=KIND_REQUESTED, request_id=request.pk, params={"actor": contact.name or contact.email}
        )
        transaction.on_commit(lambda: _notify_staff(locked))
    return request


def _notify_staff(company: Company) -> None:
    """Сотрудникам с правом подтверждать — в колокольчик Платформы; нет таких — администраторам платформы."""
    from accounts.models import CustomUser
    from core.tenant import own_company_id
    from notifications.services import notify_platform_admins, notify_user

    title = f"Запрос на смену банковских реквизитов: {company.name}"
    message = "Сверьте новый счёт с компанией и подтвердите или отклоните запрос."
    params = {"company": company.name}
    recipients = CustomUser.objects.filter(
        is_active=True,
        memberships__company_id=own_company_id(),
        memberships__is_active=True,
        memberships__company_roles__permissions__contains=["finance.payment"],
    ).distinct()
    if not recipients:
        notify_platform_admins(
            title=title,
            message=message,
            type_code="WARNING",
            event_code="portal.bank_change_requested",
            event_params=params,
        )
        return
    for user in recipients:
        notify_user(
            user=user,
            title=title,
            message=message,
            type_code="WARNING",
            link="/eds/payments?show=bank_changes",
            event_code="portal.bank_change_requested",
            event_params=params,
        )


def approve(request_id: int, *, actor) -> BankDetailsChangeRequest:
    """Подтвердить и применить. Повторное подтверждение — без второго эффекта; решённый иначе — конфликт."""
    company_id = _company_of(request_id)
    with transaction.atomic():
        company = _lock_company(company_id)
        request = BankDetailsChangeRequest.objects.select_for_update().get(pk=request_id)
        if request.status == BankDetailsChangeStatus.APPROVED:
            return request
        if request.status != BankDetailsChangeStatus.PENDING:
            raise PortalConflict(NOT_PENDING)
        if not company.is_active:
            raise PortalConflict(ARCHIVED)
        if is_stale(request, company):
            raise PortalConflict(STALE)
        company.bank_details = request.new_bank_details
        company.save(update_fields=["bank_details", "updated_at"])
        request.status = BankDetailsChangeStatus.APPROVED
        _decided(request, actor)
        request.save(update_fields=["status", "decided_by", "decided_at"])
        record_portal_security_event(
            company,
            PortalSecurityEvent.EventType.BANK_DETAILS_CHANGED,
            actor_name=STAFF_ACTOR,
            details=f"Реквизиты изменены сотрудником, счёт {mask_bank_details(request.new_bank_details) or '—'}",
        )
        notify_change(company, kind=KIND_APPROVED, request_id=request.pk)
        _audit(request, actor, "approved", "Смена реквизитов подтверждена")
    return request


def reject(request_id: int, *, actor, reason: str) -> BankDetailsChangeRequest:
    """Отклонить с причиной; реквизиты не меняются. Повтор — без второго эффекта; подтверждённый — конфликт."""
    company_id = _company_of(request_id)
    with transaction.atomic():
        company = _lock_company(company_id)
        request = BankDetailsChangeRequest.objects.select_for_update().get(pk=request_id)
        if request.status == BankDetailsChangeStatus.REJECTED:
            return request
        if request.status != BankDetailsChangeStatus.PENDING:
            raise PortalConflict(NOT_PENDING)
        request.status = BankDetailsChangeStatus.REJECTED
        request.reject_reason = reason
        _decided(request, actor)
        request.save(update_fields=["status", "reject_reason", "decided_by", "decided_at"])
        record_portal_security_event(
            company,
            PortalSecurityEvent.EventType.BANK_DETAILS_CHANGE_REJECTED,
            actor_name=STAFF_ACTOR,
            details=f"Смена реквизитов отклонена, счёт {mask_bank_details(request.new_bank_details) or '—'}",
        )
        notify_change(company, kind=KIND_REJECTED, request_id=request.pk, params={"reason": reason})
        _audit(request, actor, "rejected", "Смена реквизитов отклонена")
    return request


def is_stale(request: BankDetailsChangeRequest, company: Company) -> bool:
    return (company.formatted_bank_details or "").strip() != (request.old_bank_details or "").strip()


def _company_of(request_id: int) -> int:
    return BankDetailsChangeRequest.objects.values_list("company_id", flat=True).get(pk=request_id)


def _decided(request: BankDetailsChangeRequest, actor) -> None:
    request.decided_by = actor
    request.decided_at = timezone.now()


def _audit(request: BankDetailsChangeRequest, actor, event: str, action: str) -> None:
    """След для сотрудников: без реквизитов (маска) — журнал читают и без права подтверждать."""
    from catalog.desk.audit import record

    if actor is None:
        return
    record(
        actor,
        entity="bank_change",
        instance=request,
        event=event,
        action=action,
        before={"status": BankDetailsChangeStatus.PENDING.value},
        after={"status": request.status, "account": mask_bank_details(request.new_bank_details)},
        detail=f"{request.company.name}: {action}",
    )

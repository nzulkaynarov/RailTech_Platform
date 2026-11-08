"""Очередь запросов контрагентов на смену банковских реквизитов для бухгалтера (FX-4): чтение и сборка строки ответа.

Решение — `portal/services/bank_details_change.py`. Полные реквизиты — сотруднику с правом подтверждать (`finance.payment`);
читающему (директор, менеджер с `finance.view`) — маска: сверять счёт ему незачем.
"""

from __future__ import annotations

from portal.models import BankDetailsChangeRequest, BankDetailsChangeStatus
from portal.services.bank_details_change import is_stale, mask_bank_details

from accounts.services.permissions import staff_has_permission

FINANCE_READ = ("finance.view", "finance.payment")
FINANCE_DECIDE = "finance.payment"


def can_read(user) -> bool:
    return bool(user.is_superuser or staff_has_permission(user, FINANCE_READ))


def can_decide(user) -> bool:
    return bool(user.is_superuser or staff_has_permission(user, FINANCE_DECIDE))


def _details(value: str, *, full: bool) -> str:
    return value if full else mask_bank_details(value)


def row(item: BankDetailsChangeRequest, *, full: bool) -> dict:
    company = item.company
    decider = item.decided_by
    return {
        "id": item.pk,
        "company_id": company.pk,
        "company_name": company.name,
        "company_inn": company.inn or "",
        "company_archived": not company.is_active,
        "status": item.status,
        "stale": item.status == BankDetailsChangeStatus.PENDING and is_stale(item, company),
        "old_bank_details": _details(item.old_bank_details, full=full),
        "new_bank_details": _details(item.new_bank_details, full=full),
        "requested_by_name": item.requested_by_name,
        "requested_by_email": item.requested_by_email,
        "requested_ip": item.requested_ip,
        "created_at": item.created_at,
        "decided_at": item.decided_at,
        "decided_by_name": (decider.get_full_name() or decider.email) if decider else None,
        "reject_reason": item.reject_reason or None,
    }


def queue(*, status_filter: str | None, full: bool) -> dict:
    rows = BankDetailsChangeRequest.objects.select_related("company", "decided_by")
    pending = rows.filter(status=BankDetailsChangeStatus.PENDING).count()
    if status_filter:
        rows = rows.filter(status=status_filter)
    return {"items": [row(item, full=full) for item in rows[:200]], "pending_count": pending}

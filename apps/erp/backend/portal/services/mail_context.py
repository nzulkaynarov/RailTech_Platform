"""Кому клиент ответит на письмо входа или приглашения (B-MAIL-1): Reply-To — ответственный менеджер.

Ответ на письмо робота уходил в ящик отправителя карточки «Почта», где его никто не ждёт. Теперь, если менеджер известен,
ответ клиента попадает к нему: сотрудник, который пригласил, иначе менеджер последней сделки компании.
"""

from __future__ import annotations

from typing import Optional

from sales.models import Deal


def _email_of(user) -> Optional[str]:
    email = (getattr(user, "email", "") or "").strip()
    return email or None


def responsible_manager_email(company_id: Optional[int], actor=None) -> Optional[str]:
    """Адрес для Reply-To: сотрудник-инициатор (`actor` — пользователь ERP) или менеджер последней сделки компании."""
    if actor is not None and hasattr(actor, "pk"):
        found = _email_of(actor)
        if found:
            return found
    if company_id is None:
        return None
    deal = (
        Deal.objects.filter(company_id=company_id)
        .exclude(manager__isnull=True, assigned_to__isnull=True)
        .select_related("manager", "assigned_to")
        .order_by("-created_at", "-id")
        .first()
    )
    if deal is None:
        return None
    return _email_of(deal.manager) or _email_of(deal.assigned_to)

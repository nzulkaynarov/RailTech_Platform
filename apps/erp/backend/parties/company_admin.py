"""Администратор компании-клиента (J2, FX-6): у компании с активными контактами всегда есть активный администратор.

`is_admin` ставится только приглашением и PATCH `/team/{id}`, которые сами требуют администратора. Пути, что заводят
первого контакта без администратора (сотрудник в ERP, передача из CRM, заявка партнёра, список контактов поставщика),
вызывают `ensure_company_admin`: если администратора нет, им становится основной активный контакт, иначе самый ранний.
"""

from __future__ import annotations

from django.db import transaction
from parties.models import Company, Contact, active_contact_q


@transaction.atomic  # вне транзакции блокировка — 500; внутри внешней живёт до её коммита
def lock_company_row(company: Company) -> None:
    """Блокировка строки компании до конца транзакции: проверки состава администраторов идут по очереди."""
    Company.objects.select_for_update().filter(pk=company.pk).first()


def ensure_company_admin(company: Company) -> Contact | None:
    """Назначить администратора, если у компании с активными контактами его нет; вернуть назначенного или `None`."""
    active = Contact.objects.filter(active_contact_q(), company=company)
    if not active.exists() or active.filter(is_admin=True).exists():
        return None
    chosen = active.order_by("-is_primary", "id").first()
    chosen.is_admin = True
    chosen.save(update_fields=["is_admin", "updated_at"])
    return chosen

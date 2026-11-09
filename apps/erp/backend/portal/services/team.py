"""Команда компании в кабинете: права коллег и отключение (J2) с защитой «последнего администратора» (FX-6).

Проверка «есть ли другой администратор» и запись прав идут под блокировкой строки компании: без неё два администратора,
снимающие друг друга одновременно, оба видят «другой остался» и компания остаётся без администратора.
"""

from __future__ import annotations

from django.db import transaction
from django.http import Http404
from django.utils import timezone
from parties.company_admin import lock_company_row
from parties.models import Company, Contact, active_contact_q
from portal.exceptions import PortalValidationError
from portal.models import MagicLinkToken, PortalSession


def _has_other_admin(company: Company, target: Contact) -> bool:
    return Contact.objects.filter(active_contact_q(), company=company, is_admin=True).exclude(pk=target.pk).exists()


def _active_target(company: Company, pk: int) -> Contact:
    target = Contact.objects.filter(active_contact_q(), pk=pk, company=company).first()
    if target is None:
        raise Http404
    return target


@transaction.atomic
def update_member_rights(company: Company, target_pk: int, validated: dict) -> tuple[Contact, bool]:
    """Права коллеги (`PATCH /team/{id}`): вернуть (контакт, менялось ли что-то)."""
    lock_company_row(company)
    target = _active_target(company, target_pk)

    drops_admin = "is_admin" in validated and not validated["is_admin"]
    drops_can_act = "can_act" in validated and not validated["can_act"]

    # Защита основного контакта: статус администратора и право действовать нельзя снять
    if target.is_primary and (drops_admin or drops_can_act):
        raise PortalValidationError("CANNOT_MODIFY_PRIMARY_CONTACT")

    # Последний администратор не снимает ни статус, ни право действовать: иначе подписывать за компанию некому
    if target.is_admin and (drops_admin or drops_can_act) and not _has_other_admin(company, target):
        raise PortalValidationError("LAST_ADMIN_CANNOT_BE_REMOVED")

    fields = []
    for name in ("can_act", "is_admin"):
        if name in validated:
            setattr(target, name, validated[name])
            fields.append(name)
    if fields:
        target.save(update_fields=fields)
    return target, bool(fields)


@transaction.atomic
def deactivate_member(company: Company, actor: Contact, target_pk: int) -> Contact:
    """Отключить коллегу (`POST /team/{id}/deactivate`): архив, права сняты, сессии и ссылки входа удалены."""
    lock_company_row(company)
    target = _active_target(company, target_pk)

    if target.pk == actor.pk:
        raise PortalValidationError("CANNOT_DEACTIVATE_SELF")
    if target.is_primary:
        raise PortalValidationError("CANNOT_MODIFY_PRIMARY_CONTACT")
    if target.is_admin and not _has_other_admin(company, target):
        raise PortalValidationError("LAST_ADMIN_CANNOT_BE_REMOVED")

    target.archived_at = timezone.now()
    target.is_admin = False
    target.can_act = False
    target.save(update_fields=["archived_at", "is_admin", "can_act"])

    PortalSession.objects.filter(contact=target).delete()
    MagicLinkToken.objects.filter(contact=target).delete()
    return target

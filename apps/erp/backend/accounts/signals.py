"""
Signals of the accounts app.

A company's role (CompanyType) is an explicit mark or follows from data (offers, brands, deals) — it never appears
by itself (СЦ-8). A company whose last role was removed stays without roles and is not in the client book; the old
"restore CLIENT when the last type is removed" signal is gone. A flow that creates a company AS a client sets CLIENT
explicitly (`integration/services/handoff.py`, `accounts/services/clients.py`, `integration/services/partner_client.py`).
"""

import logging

from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from rest_framework.throttling import BaseThrottle

from .models import Company
from .services import login_guard

logger = logging.getLogger(__name__)


@receiver(user_login_failed)
def log_django_auth_login_failure(sender, credentials=None, request=None, **kwargs):
    """SEC-06 detection for Django-auth login failures (notably /admin/login/).

    simplejwt (the DRF app login) does not emit this signal — it records failures
    directly via login_guard in the view — so this only covers Django's own
    authenticate() paths (Unfold admin, management), without double-counting.
    Detection/alerting only; no lockout (see login_guard.note_django_auth_failure).
    """
    creds = credentials or {}
    username = creds.get("username") or creds.get("email") or ""
    ip = BaseThrottle().get_ident(request) if request is not None else ""
    path = getattr(request, "path", "") if request is not None else ""
    login_guard.note_django_auth_failure(username, ip, path)


# Поля карточки компании, которые печатаются в бланке EDS (решение владельца 2026-11-11: одни реквизиты).
LETTERHEAD_FIELDS = frozenset({"name", "inn", "legal_address", "logo"})  # банк — сигналы счетов ниже


@receiver(post_save, sender=Company)
def publish_letterhead_on_requisites(sender, instance: Company, created: bool, update_fields=None, **kwargs):
    """Любая правка реквизитов своей компании (Настройки, мастер первого запуска, синхронизация с CRM) обновляет бланк
    в EDS. Раньше бланк уходил только при сохранении вкладки «Бланк», и письмо отвечало «Бланк компании не задан»."""
    if kwargs.get("raw"):
        return
    if update_fields is not None and not LETTERHEAD_FIELDS & set(update_fields):
        return
    from django.core.exceptions import ImproperlyConfigured

    from .services.letterhead_event import publish_company_letterhead

    try:
        publish_company_letterhead(instance)
    except ImproperlyConfigured:  # своя компания не определена (несколько продавцов без OWN_COMPANY_ID) — бланка нет
        logger.info("letterhead not published: own company is ambiguous", exc_info=True)


def _publish_for(company) -> None:
    from django.core.exceptions import ImproperlyConfigured

    from .services.letterhead_event import publish_company_letterhead

    try:
        publish_company_letterhead(company)
    except ImproperlyConfigured:
        logger.info("letterhead not published: own company is ambiguous", exc_info=True)


@receiver(post_save, sender="parties.CompanyBankAccount")
@receiver(post_delete, sender="parties.CompanyBankAccount")
def publish_letterhead_on_bank_account(sender, instance, **kwargs):
    """Счета своей компании — тоже реквизиты бланка (решение владельца 2026-11-11)."""
    if kwargs.get("raw"):
        return
    _publish_for(instance.company)

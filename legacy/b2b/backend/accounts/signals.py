"""
Invariant: every Company must have at least one CompanyType.
Otherwise the frontend cannot derive a status context (BUYER/SELLER/MANUFACTURER)
and Admin-role users get bounced to ProfileCompletionForm when they open the app.

Default restoration: CLIENT for ALL companies — including the RailTech company
itself. RailTech on the platform is an equal participant; super-rights belong
exclusively to the `admin@railtech.uz` user account (is_superuser + SystemRole.ADMIN),
NOT to the RailTech company. If RailTech's company needs to act as a seller, a
human must add SUPPLIER to its types through normal Admin UI — no magic bypass.

Mirrors the backfill in core/migrations/0002_seed_enterprise_lookups.py, but
applied on every M2M-edit, not once per migrate.
"""

import logging

from django.contrib.auth.signals import user_login_failed
from django.db.models.signals import m2m_changed
from django.dispatch import receiver
from rest_framework.throttling import BaseThrottle

from .models import Company, CompanyType
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


@receiver(m2m_changed, sender=Company.types.through)
def ensure_company_has_at_least_one_type(sender, instance: Company, action: str, **kwargs):
    """Guard Company.types M2M. Re-adds CLIENT if the last type was removed."""
    if action not in {"post_remove", "post_clear"}:
        return
    if instance.types.exists():
        return
    ct = CompanyType.objects.filter(code="CLIENT").first()
    if ct is None:
        logger.warning(
            "Company %s has no types and CompanyType(CLIENT) is not seeded — "
            "run `python manage.py migrate` to apply core.0002_seed_enterprise_lookups",
            instance.pk,
        )
        return
    instance.types.add(ct)
    logger.info(
        "Company %s had no types left after %s — auto-restored CLIENT default",
        instance.pk,
        action,
    )


@receiver(m2m_changed, sender=Company.types.through)
def supplier_or_manufacturer_implies_client(sender, instance: Company, action: str, pk_set, **kwargs):
    """Business rule: a SELLER (SUPPLIER) company is also allowed to buy.

    Source: user directive 2026-04-19 — a company that becomes a seller automatically
    gains CLIENT (buyer) capability. (MANUFACTURER retired as a role 2026-06-23 —
    sellers are SUPPLIER; OEM is now only catalog.Manufacturer.)
    """
    if action != "post_add" or not pk_set:
        return
    added = set(
        CompanyType.objects.filter(pk__in=pk_set).values_list("code", flat=True),
    )
    if not added & {"SUPPLIER"}:
        return
    if instance.types.filter(code="CLIENT").exists():
        return
    client = CompanyType.objects.filter(code="CLIENT").first()
    if client is None:
        return
    instance.types.add(client)
    logger.info(
        "Company %s received %s — auto-granted CLIENT capability (can buy).",
        instance.pk,
        added,
    )

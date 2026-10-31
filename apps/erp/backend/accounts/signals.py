"""
Invariant: every Company must have at least one CompanyType.
Otherwise the frontend cannot derive a status context (BUYER/SELLER/MANUFACTURER)
and Admin-role users get bounced to ProfileCompletionForm when they open the app.

Default restoration: CLIENT for companies left WITHOUT any type. Super-rights belong
exclusively to the superuser account (is_superuser + SystemRole.ADMIN).
If a company needs to act as a seller, a human must add SUPPLIER to its types
through normal Admin UI — no magic bypass. SUPPLIER does NOT imply CLIENT (K0, 2026-11-01):
the marketplace rule "a seller may also buy" is gone, and CLIENT is what opens the
client cabinet (`portal/services/access.py`), so a supplier must not get it for free.

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

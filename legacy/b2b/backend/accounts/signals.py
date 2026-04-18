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

from django.db.models.signals import m2m_changed
from django.dispatch import receiver

from .models import Company, CompanyType

logger = logging.getLogger(__name__)


@receiver(m2m_changed, sender=Company.types.through)
def ensure_company_has_at_least_one_type(sender, instance: Company, action: str, **kwargs):
    """Guard Company.types M2M. Re-adds CLIENT if the last type was removed."""
    if action not in {'post_remove', 'post_clear'}:
        return
    if instance.types.exists():
        return
    ct = CompanyType.objects.filter(code='CLIENT').first()
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
        instance.pk, action,
    )


@receiver(m2m_changed, sender=Company.types.through)
def supplier_or_manufacturer_implies_client(sender, instance: Company, action: str, pk_set, **kwargs):
    """Business rule: SUPPLIER or MANUFACTURER companies are also allowed to buy.

    Source: user directive 2026-04-19 — «любая компания, выбравшая SUPPLIER или
    MANUFACTURER, автоматически получает право быть CLIENT (покупателем)».
    """
    if action != 'post_add' or not pk_set:
        return
    added = set(
        CompanyType.objects.filter(pk__in=pk_set).values_list('code', flat=True),
    )
    if not added & {'SUPPLIER', 'MANUFACTURER'}:
        return
    if instance.types.filter(code='CLIENT').exists():
        return
    client = CompanyType.objects.filter(code='CLIENT').first()
    if client is None:
        return
    instance.types.add(client)
    logger.info(
        "Company %s received %s — auto-granted CLIENT capability (can buy).",
        instance.pk, added,
    )

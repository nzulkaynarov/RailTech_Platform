from django.utils.translation import gettext_lazy as _

from core.models import AbstractLookup


class InvoiceStatus(AbstractLookup):
    """Статусы инвойса. Seed: DRAFT, ISSUED, PARTIAL, PAID, OVERDUE, CANCELLED."""

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус инвойса")
        verbose_name_plural = _("Справочник: Статусы инвойсов")


class ActStatus(AbstractLookup):
    """Статусы акта. Seed: DRAFT, ISSUED, SIGNED, CANCELLED."""

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус акта")
        verbose_name_plural = _("Справочник: Статусы актов")


__all__ = [
    "ActStatus",
    "InvoiceStatus",
]

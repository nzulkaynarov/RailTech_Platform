from django.utils.translation import gettext_lazy as _

from core.models import AbstractLookup


class DealStage(AbstractLookup):
    """
    Этапы воронки сделки.
    Seed: DRAFT, KYC_PENDING, CALCULATING, QUOTE_SENT, CONTRACT_SIGNED, CLOSED_WON, CLOSED_LOST
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Этап сделки")
        verbose_name_plural = _("Справочник: Этапы сделок")


class QuoteStatus(AbstractLookup):
    """
    Статусы коммерческих предложений.
    Seed: DRAFT, SENT, APPROVED, REJECTED, EXPIRED
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус КП")
        verbose_name_plural = _("Справочник: Статусы КП")


class ContractStatus(AbstractLookup):
    """Статусы контракта. Seed: DRAFT, PENDING_CLIENT, PENDING_MANAGER, SIGNED, CANCELLED."""

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус контракта")
        verbose_name_plural = _("Справочник: Статусы контрактов")


class FulfillmentStatus(AbstractLookup):
    """Статусы исполнения/отгрузки. Seed: PENDING, SHIPPED, IN_TRANSIT, DELIVERED, ACCEPTED, DISPUTED."""

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус исполнения")
        verbose_name_plural = _("Справочник: Статусы исполнения")


class ChargeType(AbstractLookup):
    """
    Справочник статей расхода уровня КП (UBL 2.1 document-level cac:AllowanceCharge).
    Seed-минимум: FREIGHT, INSURANCE, CUSTOMS, CERTIFICATION, RENT, PAYROLL, COMMISSION, OTHER.
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статья расхода")
        verbose_name_plural = _("Справочник: Статьи расхода КП")


__all__ = [
    "ChargeType",
    "ContractStatus",
    "DealStage",
    "FulfillmentStatus",
    "QuoteStatus",
]

from django.utils.translation import gettext_lazy as _

from master_data.models import AbstractLookup

# ────────────────────────────────────────────
# Справочники модуля CRM
# ────────────────────────────────────────────


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


# Post-sale document statuses (F5.4) — moved from inline CharField choices to FK
# lookups so they share one source of truth with Deal/Quote (code↔row contract in
# crm.constants; rows seeded in a data migration). Codes: see crm/constants.py.


class ContractStatus(AbstractLookup):
    """Статусы контракта. Seed: DRAFT, PENDING_CLIENT, PENDING_MANAGER, SIGNED, CANCELLED."""

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус контракта")
        verbose_name_plural = _("Справочник: Статусы контрактов")


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


class FulfillmentStatus(AbstractLookup):
    """Статусы исполнения/отгрузки. Seed: PENDING, SHIPPED, IN_TRANSIT, DELIVERED, ACCEPTED, DISPUTED."""

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статус исполнения")
        verbose_name_plural = _("Справочник: Статусы исполнения")


class ChargeType(AbstractLookup):
    """
    Справочник статей расхода уровня КП (UBL 2.1 document-level cac:AllowanceCharge).

    Овнер компании пополняет список: фрахт, страховка, аренда склада, ЗП проектной
    команды, комиссионные выплаты, сертификация, таможенный штраф и т.п. Эти статьи
    добавляются на ВЕСЬ КП (не на позицию) и входят в TaxExclusiveAmount до НДС.
    Seed-минимум: FREIGHT, INSURANCE, CUSTOMS, CERTIFICATION, RENT, PAYROLL, COMMISSION, OTHER.
    """

    class Meta(AbstractLookup.Meta):
        verbose_name = _("Статья расхода")
        verbose_name_plural = _("Справочник: Статьи расхода КП")

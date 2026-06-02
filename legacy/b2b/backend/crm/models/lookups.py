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

"""Single source of truth for CRM lookup CODES (DealStage, QuoteStatus).

Reference these in services/views instead of bare string literals so a typo is an
AttributeError, not a silent runtime miss. The lookup rows themselves stay in the
DB (names, i18n, sort_order) — this is the stable code↔data contract.

NB: do NOT import this from migrations — migrations must stay frozen.
"""

from django.db import models


class DealStageCode(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    KYC_PENDING = "KYC_PENDING", "Ожидание KYC"
    RFQ_OPEN = "RFQ_OPEN", "RFQ открыт"
    SOURCING = "SOURCING", "Подбор поставщиков"
    CALCULATING = "CALCULATING", "Расчёт цен"
    QUOTE_SENT = "QUOTE_SENT", "КП отправлено"
    CONTRACT_SIGNED = "CONTRACT_SIGNED", "Договор подписан"
    CLOSED_WON = "CLOSED_WON", "Закрыта (успех)"
    CLOSED_LOST = "CLOSED_LOST", "Закрыта (отказ)"


class QuoteStatusCode(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    PENDING_TRADE_REVIEW = "PENDING_TRADE_REVIEW", "На проверке ВЭД"
    PENDING_APPROVAL = "PENDING_APPROVAL", "На утверждении"
    READY_TO_SEND = "READY_TO_SEND", "Готово к отправке"
    SENT = "SENT", "Отправлено клиенту"
    APPROVED = "APPROVED", "Одобрено"
    REJECTED = "REJECTED", "Отклонено"

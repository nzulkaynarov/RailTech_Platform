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


# Канонический порядок этапов в воронке — ЕДИНСТВЕННЫЙ источник sort_order для DealStage.
# Его читают: data-миграция починки порядка (crm/0076), dev-сид (core_seed) и guard-тест.
# Ресерч 2026-07-28: ранние сиды создали этапы с порядком 0-7 БЕЗ RFQ_OPEN; добавленный позже
# RFQ_OPEN получил хвостовой 25, а get_or_create сид-миграции существующие строки не чинит —
# «Заявка открыта» падала В КОНЕЦ дропдауна/канбана/воронки, после закрытых сделок.
DEAL_STAGE_CANONICAL_ORDER = {
    DealStageCode.DRAFT: 10,
    DealStageCode.KYC_PENDING: 20,
    DealStageCode.RFQ_OPEN: 30,
    DealStageCode.SOURCING: 40,
    DealStageCode.CALCULATING: 50,
    DealStageCode.QUOTE_SENT: 60,
    DealStageCode.CONTRACT_SIGNED: 70,
    DealStageCode.CLOSED_WON: 80,
    DealStageCode.CLOSED_LOST: 90,
}


class QuoteStatusCode(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    PENDING_TRADE_REVIEW = "PENDING_TRADE_REVIEW", "На проверке ВЭД"
    PENDING_APPROVAL = "PENDING_APPROVAL", "На утверждении"
    READY_TO_SEND = "READY_TO_SEND", "Готово к отправке"
    SENT = "SENT", "Отправлено клиенту"
    APPROVED = "APPROVED", "Одобрено"
    REJECTED = "REJECTED", "Отклонено"


# ── Post-sale status codes ──────────────────────────────────────────────────
# These mirror the CharField(choices=...) values on the Contract / Invoice /
# Act / Fulfillment models. The models keep their inline choices for the admin
# UI; services/tasks reference these constants instead of bare string literals
# so a typo is an AttributeError, not a silent runtime miss. Values MUST stay
# byte-for-byte identical to the model choices.


class ContractStatusCode(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    PENDING_CLIENT = "PENDING_CLIENT", "Ожидает подписи клиента"
    PENDING_MANAGER = "PENDING_MANAGER", "Ожидает подписи менеджера"
    SIGNED = "SIGNED", "Подписан сторонами"
    CANCELLED = "CANCELLED", "Отменён"


class InvoiceStatusCode(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    ISSUED = "ISSUED", "Выставлен"
    PARTIAL = "PARTIAL", "Частично оплачен"
    PAID = "PAID", "Оплачен"
    OVERDUE = "OVERDUE", "Просрочен"
    CANCELLED = "CANCELLED", "Отменён"


class ActStatusCode(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    ISSUED = "ISSUED", "Выставлен"
    SIGNED = "SIGNED", "Подписан"
    CANCELLED = "CANCELLED", "Отменён"


class FulfillmentStatusCode(models.TextChoices):
    PENDING = "PENDING", "Ожидает отгрузки"
    SHIPPED = "SHIPPED", "Отгружено"
    IN_TRANSIT = "IN_TRANSIT", "В пути"
    DELIVERED = "DELIVERED", "Доставлено"
    ACCEPTED = "ACCEPTED", "Принято клиентом"
    DISPUTED = "DISPUTED", "Спорная ситуация"


# ── «Документы 2.0» — arbitrary template-based documents (letters, reports) ──
# Lookup CODES mirroring the DocumentTemplateKind / GeneratedDocumentStatus rows
# seeded by a data migration (IRON RULE 1). Referenced from services by code.


class DocumentTemplateKindCode(models.TextChoices):
    LETTER = "LETTER", "Письмо"
    REPORT = "REPORT", "Рапорт / отчёт"
    CUSTOM = "CUSTOM", "Произвольный"
    # Юридические виды (spec-editable-outgoing-documents): компания правит СВОЙ шаблон
    # договора / счёта / акта, а не строки в коде. Пока своего шаблона нет — печатается
    # платформенный образец, то есть документ не меняется.
    CONTRACT = "CONTRACT", "Договор"
    INVOICE = "INVOICE", "Счёт"
    ACT = "ACT", "Акт"


#: Виды, у которых документ юридический: для них шаблон обязан содержать реквизиты (E2), а
#: правка вёрстки блоков запрещена — блок вставляется целиком одним плейсхолдером.
LEGAL_TEMPLATE_KINDS = frozenset(
    {DocumentTemplateKindCode.CONTRACT, DocumentTemplateKindCode.INVOICE, DocumentTemplateKindCode.ACT}
)


class GeneratedDocumentStatusCode(models.TextChoices):
    DRAFT = "DRAFT", "Черновик"
    ISSUED = "ISSUED", "Выпущен"
    CANCELLED = "CANCELLED", "Отменён"


#: Срок оплаты счёта по умолчанию, дней. Отсчитывается от даты ВЫСТАВЛЕНИЯ счёта
#: (`issue_invoice`), а не от создания черновика: черновик может пролежать неделю, и срок
#: оплаты «съедался» бы ещё до того, как покупатель вообще увидел счёт. Эталоны (Odoo, Stripe,
#: QuickBooks) считают срок от даты выставления.
#: Значение было зашито числом в четырёх местах — вынесено, чтобы его можно было менять в
#: одном месте и позже заменить настройкой компании.
DEFAULT_INVOICE_DUE_DAYS = 14

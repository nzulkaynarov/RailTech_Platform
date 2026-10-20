"""Стадия и сумма сделки на языке контракта шва CRM ↔ ERP (`erp-integration.yaml` 0.2.0, FIX-30).

Единственное место, где ERP превращает свои данные в `DealStage` контракта. Ответы integration (`summary.py`),
`DealRef` во всех событиях (`webhooks.py`), сигналы смены стадии (`signals.py`), передача клиента (`handoff.py`) и
инструменты MCP (FIX-36) берут стадию и сумму отсюда. Сырого кода FSM (`deal.stage.code`) в ответы и события не
попадает: читать его можно только здесь (`fsm_code`).

Публичный интерфейс для следующих задач:

* `deal_stage(deal) -> str` — код `DealStage` контракта;
* `deal_amount(deal) -> Decimal | None` — сумма последней версии КП, видимого клиенту, иначе `None`;
* `deal_currency(deal) -> str` — валюта той же версии КП;
* `with_stage_facts(queryset)` — подгрузка связей, чтобы список сделок не ходил в базу на каждую (N+1);
* `initial_fsm_stage()` — стадия FSM, с которой начинается заявка (как у заявки из портала).

Откуда стадия. FSM ERP (`crm/services/deals.py`) знает только девять кодов, а контракт — одиннадцать, и две шкалы
не совпадают по смыслу: `CONTRACT_SIGNED` ставится при акцепте КП (договор ещё не подписан), а `CLOSED_WON` — при
подписании договора обеими сторонами, ДО счёта, оплаты и поставки (`crm/services/contracts.py`,
`deal_execution_is_complete`: «выиграна» и «исполнена» — разные шкалы). Поэтому до акцепта стадию даёт FSM, после
акцепта — документы сделки (то, что клиент видит в Cabinet), а `won` наступает, когда исполнение закрыто целиком.

Правила (сверху вниз, срабатывает первое):

| Условие                                                                             | Стадия контракта |
|-------------------------------------------------------------------------------------|------------------|
| FSM `CLOSED_LOST`                                                                   | `lost`           |
| FSM `CLOSED_WON` и исполнение закрыто целиком (счета оплачены, акты подписаны,      | `won`            |
| поставка принята — `deal_execution_is_complete`)                                    |                  |
| FSM `CONTRACT_SIGNED` / `CLOSED_WON` (КП акцептовано) и есть видимый клиенту акт    | `closing`        |
| (выставлен, подписан или возвращён)                                                 |                  |
| …и поставка пошла: исполнение сделки не `PENDING` либо строка поставки не           | `fulfilment`     |
| `assembling`                                                                        |                  |
| …и все видимые клиенту неаннулированные счета оплачены (их не меньше одного)        | `paid`           |
| …и есть видимый клиенту неаннулированный счёт (выставлен, оплачен частично или нет) | `invoiced`       |
| …и есть видимый клиенту договор (на подписи или подписан) либо FSM `CLOSED_WON`     | `contract`       |
| …иначе (КП акцептовано, договора для клиента ещё нет)                               | `accepted`       |
| FSM `QUOTE_SENT`                                                                    | `quote_sent`     |
| FSM `SOURCING`, `CALCULATING`                                                       | `quoting`        |
| FSM `DRAFT`, `KYC_PENDING`, `RFQ_OPEN` или стадии нет                               | `request`        |
| неизвестный код FSM (в журнал — предупреждение)                                     | `request`        |

Стадия — «самая дальняя достигнутая веха»: поставка пошла до полной оплаты — всё равно `fulfilment`. Видимость
документов клиенту — те же предикаты, что в портале (`portal/projections.py`), без копий.

Сумма. `deal_amount` — `total_incl_vat` последней версии КП в статусах, видимых клиенту
(`projections.CLIENT_QUOTE_STATUSES`: отправлено, принято, отклонено, истёк срок), иначе `None`: черновик и КП
на согласовании клиенту не обещаны и в сумму сделки не входят (хвост FIX-12). Отклонённое и просроченное КП было
отправлено, поэтому его сумма остаётся, пока нет более новой отправленной версии (Q-FIX30-3).
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Optional

from django.db.models import Prefetch, QuerySet
from portal import projections
from sales.models import DeliveryLineStatus

from crm.constants import DealStageCode, FulfillmentStatusCode, InvoiceStatusCode
from crm.models import Act, Contract, DealStage, Invoice, Quote

logger = logging.getLogger(__name__)

#: Коды `DealStage` контракта в порядке жизненного цикла (`erp-integration.yaml`, `events.schema.json`).
DEAL_STAGES = (
    "request",
    "quoting",
    "quote_sent",
    "accepted",
    "contract",
    "invoiced",
    "paid",
    "fulfilment",
    "closing",
    "won",
    "lost",
)
#: Стадии закрытой сделки: в «открытые» они не попадают.
CLOSED_STAGES = frozenset({"won", "lost"})

_REQUEST_FSM = frozenset({DealStageCode.DRAFT, DealStageCode.KYC_PENDING, DealStageCode.RFQ_OPEN})
_QUOTING_FSM = frozenset({DealStageCode.SOURCING, DealStageCode.CALCULATING})
_ACCEPTED_FSM = frozenset({DealStageCode.CONTRACT_SIGNED, DealStageCode.CLOSED_WON})

#: «Не задан»: отличает `with_fsm_code=None` («стадии не было») от «взять код у сделки».
_FROM_DEAL: Any = object()


def is_deal_stage(code: Any) -> bool:
    return code in DEAL_STAGES


def is_open_stage(stage: str) -> bool:
    return stage not in CLOSED_STAGES


def fsm_code(deal) -> Optional[str]:
    """Код стадии FSM сделки (`DealStageCode`); `None` — стадии нет. Единственное чтение `stage.code` в integration."""
    return deal.stage.code if deal.stage_id else None


def fsm_outcome(code: Optional[str]) -> Optional[str]:
    """Итог по коду FSM: `won` / `lost` / `None`. Нужен сигналам для `deal.won` и `deal.lost` (итог продажи — по FSM)."""
    if code == DealStageCode.CLOSED_WON:
        return "won"
    if code == DealStageCode.CLOSED_LOST:
        return "lost"
    return None


def initial_fsm_stage() -> Optional[DealStage]:
    """Стадия FSM новой заявки: `DRAFT`, как у заявки из портала (`portal/services/requests.py`)."""
    return DealStage.objects.filter(code=DealStageCode.DRAFT).first()


def with_stage_facts(queryset: QuerySet) -> QuerySet:
    """Подгружает всё, что читают `deal_stage` и `deal_amount`: список сделок идёт без запроса на каждую."""
    return queryset.select_related("stage", "company", "fulfillment__status").prefetch_related(
        Prefetch("quotes", queryset=Quote.objects.select_related("status", "quote_currency")),
        Prefetch("contracts", queryset=Contract.objects.select_related("status")),
        Prefetch("invoices", queryset=Invoice.objects.select_related("status", "currency")),
        Prefetch("acts", queryset=Act.objects.select_related("status")),
        "delivery_lines",
    )


# ── Сумма ───────────────────────────────────────────────────────────────────────────────────────────


def sent_quote(deal) -> Optional[Quote]:
    """Последняя версия КП в статусах, видимых клиенту; `None` — клиенту КП ещё не отправлялось."""
    visible = [q for q in deal.quotes.all() if q.status_id and q.status.code in projections.CLIENT_QUOTE_STATUSES]
    return max(visible, key=lambda quote: quote.version) if visible else None


def deal_amount(deal) -> Optional[Decimal]:
    """Сумма сделки с НДС: последняя отправленная клиенту версия КП, иначе `None` (черновики не в счёт)."""
    quote = sent_quote(deal)
    return Decimal(quote.total_incl_vat) if quote is not None else None


def deal_currency(deal) -> str:
    """Валюта суммы: валюта отправленной версии КП, иначе последней версии, иначе валюта по умолчанию."""
    quote = sent_quote(deal)
    if quote is None:
        quotes = list(deal.quotes.all())
        quote = max(quotes, key=lambda q: q.version) if quotes else None
    return projections.currency_code(quote.quote_currency if quote is not None else None)


# ── Стадия ──────────────────────────────────────────────────────────────────────────────────────────


def _fulfilment_started(deal) -> bool:
    """Поставка пошла: исполнение сделки вышло из `PENDING` либо строка поставки вышла из `assembling`.

    Исполнение (`Fulfillment`) заводится сразу при подписании договора со статусом `PENDING`, поэтому сам факт его
    существования стадию не двигает.
    """
    fulfillment = getattr(deal, "fulfillment", None)
    code = getattr(getattr(fulfillment, "status", None), "code", None)
    if code and code != FulfillmentStatusCode.PENDING:
        return True
    return any(line.status != DeliveryLineStatus.ASSEMBLING for line in deal.delivery_lines.all())


def _stage_after_acceptance(deal, code: str) -> str:
    """Стадия сделки, КП которой принято: по документам (см. таблицу в docstring модуля)."""
    from crm.services.deal_documents import deal_execution_is_complete

    if code == DealStageCode.CLOSED_WON and deal_execution_is_complete(deal):
        return "won"
    if any(projections.client_acts_visible(act) for act in deal.acts.all()):
        return "closing"
    if _fulfilment_started(deal):
        return "fulfilment"
    invoices = [
        invoice
        for invoice in deal.invoices.all()
        if projections.client_invoices_visible(invoice) and invoice.status_code != InvoiceStatusCode.CANCELLED
    ]
    if invoices:
        return "paid" if all(invoice.status_code == InvoiceStatusCode.PAID for invoice in invoices) else "invoiced"
    if code == DealStageCode.CLOSED_WON or any(
        projections.client_contracts_visible(contract) for contract in deal.contracts.all()
    ):
        return "contract"
    return "accepted"


def deal_stage(deal, *, with_fsm_code: Any = _FROM_DEAL) -> str:
    """Код `DealStage` контракта для сделки: ЕДИНСТВЕННАЯ функция сопоставления, правила — в docstring модуля.

    `with_fsm_code` — только для сигнала смены стадии: «какой была бы стадия при прежнем коде FSM и нынешних
    документах» (`None` — стадии не было).
    """
    code = fsm_code(deal) if with_fsm_code is _FROM_DEAL else with_fsm_code
    if code == DealStageCode.CLOSED_LOST:
        return "lost"
    if code in _ACCEPTED_FSM:
        return _stage_after_acceptance(deal, code)
    if code == DealStageCode.QUOTE_SENT:
        return "quote_sent"
    if code in _QUOTING_FSM:
        return "quoting"
    if code is None or code in _REQUEST_FSM:
        return "request"
    logger.warning("Deal #%s: неизвестный код стадии FSM %r — отдаём «request»", getattr(deal, "pk", None), code)
    return "request"

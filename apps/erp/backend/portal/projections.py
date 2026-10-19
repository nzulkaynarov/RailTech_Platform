"""Проекции сущностей ERP на язык контракта портала (`erp-portal.yaml` 0.2.0, FIX-21).

Чистые функции без обращения к request: статусы ERP → статусы контракта, строки КП и строки поставки, источник
запроса. Сериализаторы (`portal/serializers.py`) только раскладывают результат по полям контракта, поэтому форма
ответа живёт в одном месте, а сторож (`portal/tests/test_contract_guard.py`) проверяет её по JSON Schema.

Что клиенту видно (FIX-22): КП — только отправленные (`CLIENT_QUOTE_STATUSES`), договоры — на подписи и подписанные
(`CLIENT_CONTRACT_STATUSES`), акты — выставленные, принятые и возвращённые (`client_acts_q`), счета — выставленные.
Правила жизненного цикла (кто и когда подписывает, приёмка) — в сервисах ERP, а не здесь.
Если данных для поля в модели нет, отдаётся `None`, а не выдуманное значение (вопросы — `docs/QUESTIONS.md`).
"""

from __future__ import annotations

import datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Optional

from django.db.models import Q
from django.utils import timezone

from crm.constants import ActStatusCode, ContractStatusCode, DealStageCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import ActivityLog
from crm.services.documents.projection import client_projection_items
from crm.services.quotes.access import _EXPIRED_STATUS_CODE

DEFAULT_CURRENCY = "UZS"
_CENT = Decimal("0.01")

#: КП, которые видит клиент: ушедшие к нему (`SENT`), решённые им и просроченные (`EXPIRED` ставит ночная задача
#: `crm.expire_stale_quotes` — КП не должно пропадать у клиента на следующий день после срока). Всё, что до отправки (черновик, проверка ВЭД,
#: согласование, «готово к отправке»), в портале — 404: у такого КП нет публичной ссылки (`Quote.public_url` в
#: контракте обязателен), а содержимое ещё не обещано клиенту.
CLIENT_QUOTE_STATUSES = (QuoteStatusCode.SENT, QuoteStatusCode.APPROVED, QuoteStatusCode.REJECTED, _EXPIRED_STATUS_CODE)
#: Договоры, которые видит клиент: ждёт подписи кого-то из сторон или подписан. Черновик и отменённый — нет.
CLIENT_CONTRACT_STATUSES = (
    ContractStatusCode.PENDING_CLIENT,
    ContractStatusCode.PENDING_MANAGER,
    ContractStatusCode.SIGNED,
)


# ── Деньги и сделка ───────────────────────────────────────────────────────────────────────────────


def format_amount(value) -> str:
    """Контракт `Amount`: строка `-?\\d+\\.\\d{2}`; `None` — ноль."""
    return str(Decimal(value if value is not None else 0).quantize(_CENT, rounding=ROUND_HALF_UP))


def money(value, currency_code: Optional[str]) -> dict:
    return {"amount": format_amount(value), "currency": currency_code or DEFAULT_CURRENCY}


def currency_code(currency) -> str:
    return currency.code if currency is not None else DEFAULT_CURRENCY


def deal_number(deal) -> str:
    """Номер сделки для клиента: у сделки нет собственного номера (QUESTIONS Q-FIX21-3) — `D-<id>`."""
    return f"D-{deal.pk}"


def request_number(deal) -> str:
    return f"Z-{deal.pk}"


def blank_to_none(value):
    return value if value not in ("", None) else None


# ── Запросы клиента ───────────────────────────────────────────────────────────────────────────────


def request_status(deal) -> str:
    """Статус запроса по стадии сделки и её КП (`RequestStatus`). Работает на prefetch `quotes__status`."""
    code = deal.stage.code if deal.stage else DealStageCode.DRAFT
    if code in (DealStageCode.CLOSED_WON, DealStageCode.CLOSED_LOST):
        return "closed"
    quotes = list(deal.quotes.all())
    if code in (DealStageCode.QUOTE_SENT, DealStageCode.CONTRACT_SIGNED):
        return "quoted"
    if any((q.status.code if q.status else QuoteStatusCode.DRAFT) != QuoteStatusCode.DRAFT for q in quotes):
        return "quoted"
    if code == DealStageCode.DRAFT and not quotes:
        return "new"
    return "in_progress"


def annotate_request_sources(deals: Iterable) -> None:
    """Ставит `deal.portal_source` (`crm|cabinet|erp`) одним запросом к журналу «сделка создана».

    В модели сделки источника нет (QUESTIONS Q-FIX21-4), поэтому берём факт из журнала: портал пишет
    `source=cabinet`, сотрудник ERP — запись с `actor_email` (источник `erp`); сделка без записи создания пришла
    через интеграцию с CRM (передача, MCP).
    """
    deals = list(deals)
    if not deals:
        return
    created = {
        log.deal_id: log.event_params or {}
        for log in ActivityLog.objects.filter(deal_id__in=[d.pk for d in deals], event_code="deal.created")
        .only("deal_id", "event_params")
        .order_by("-id")
    }
    for deal in deals:
        params = created.get(deal.pk)
        if params is None:
            deal.portal_source = "crm"
        elif params.get("source") in ("crm", "cabinet", "erp"):
            deal.portal_source = params["source"]
        else:
            deal.portal_source = "erp"


def request_source(deal) -> str:
    if not hasattr(deal, "portal_source"):
        annotate_request_sources([deal])
    return deal.portal_source


# ── КП ───────────────────────────────────────────────────────────────────────────────────────────


def quote_status(quote) -> str:
    code = quote.status.code if quote.status else QuoteStatusCode.DRAFT
    if code == QuoteStatusCode.APPROVED:
        return "accepted"
    if code == QuoteStatusCode.REJECTED:
        return "rejected"
    if code == _EXPIRED_STATUS_CODE:
        return "expired"
    if quote.valid_until and quote.valid_until < timezone.localdate():
        return "expired"
    if quote.first_viewed_at:
        return "viewed"
    return "sent"


def quote_number(quote) -> str:
    return quote.number or f"Q-{quote.pk}"


def quote_sent_at(quote) -> datetime.datetime:
    """Когда КП ушло клиенту: момент заморозки цен при отправке. У КП, не прошедшего отправку, — дата создания."""
    return quote.frozen_at or quote.created_at


def quote_public_url(quote) -> Optional[str]:
    from crm.services.documents.public_page import public_quote_url

    return public_quote_url(quote)


def quote_rejected_reason(quote) -> Optional[str]:
    """Причина отказа клиента — из журнала `quote.rejected` (версия в параметрах события); нет записи — `None`."""
    if quote_status(quote) != "rejected":
        return None
    logs = ActivityLog.objects.filter(deal_id=quote.deal_id, event_code="quote.rejected").order_by("-id")
    for log in logs.only("event_params"):
        params = log.event_params or {}
        if params.get("version") == quote.version:
            return blank_to_none(params.get("reason"))
    return None


def quote_lines(quote) -> list[dict]:
    """Строки КП для клиента — та же клиентская проекция, что у PDF и публичной страницы (`client_projection_items`).

    Статьи расходов уже разнесены по ценам позиций, себестоимости, наценки и НДС в строках нет; разделы и заметки
    не теряются. Суммы строк — без НДС (как в PDF), итог КП — с НДС (QUESTIONS Q-FIX21-2).
    """
    currency = currency_code(quote.quote_currency)
    lines = []
    for number, row in enumerate(client_projection_items(quote), start=1):
        kind = row["display_type"].lower()
        if kind not in ("section", "note"):
            kind = "item"
        line = {
            "line_no": number,
            "kind": kind,
            "title": row.get("imported_raw_name") or "",
            "description": "",
            "quantity": None,
            "unit": None,
            "unit_price": None,
            "total": None,
            "promised_date": None,
        }
        if kind == "item":
            product = row.get("product")
            # Название — как в PDF КП: карточка каталога, иначе строка клиента.
            line["title"] = (product.name if product else "") or row.get("imported_raw_name") or ""
            line["description"] = " · ".join(part for part in (row.get("mpn"), row.get("gost_drawing")) if part)
            line["quantity"] = str(row["quantity"])
            line["unit"] = blank_to_none(row.get("unit")) or (
                blank_to_none(product.uom.name) if product and product.uom_id else None
            )
            line["unit_price"] = money(row["final_price_excl_vat"], currency)
            line["total"] = money(row["line_total"], currency)
        lines.append(line)
    return lines


# ── Договоры, счета, акты ────────────────────────────────────────────────────────────────────────


def contract_status(contract) -> str:
    """`PENDING_CLIENT` с подписью компании — `signed_by_company`.

    Черновик и отменённый договор клиенту не показываются (`CLIENT_CONTRACT_STATUSES`): раньше черновик выдавался за
    `sent`, и Cabinet рисовал у него кнопку «Подписать». Теперь это ошибка вызова, а не молчаливая подмена.
    """
    code = contract.status.code if contract.status else ContractStatusCode.DRAFT
    if code not in CLIENT_CONTRACT_STATUSES:
        raise ValueError(f"договор в статусе {code} клиенту не показывается")
    if code == ContractStatusCode.SIGNED:
        return "signed"
    if code == ContractStatusCode.PENDING_MANAGER:
        return "signed_by_client"
    if contract.manager_signed_at:
        return "signed_by_company"
    return "sent"


def invoice_due_date(invoice) -> Optional[datetime.date]:
    """Срок оплаты счёта для клиента (в контракте обязателен).

    Берётся из счёта. Если срока нет, он считается тем же правилом, по которому ERP ставит его при выставлении
    (`issue_invoice`): дата выставления + срок оплаты продавца (`crm.services.billing.invoice_due_days`). Нет и даты
    выставления — счёт не выставлен, срок выдумывать не из чего (`None`; такой счёт клиенту не показывают).
    """
    if invoice.due_date:
        return invoice.due_date
    if invoice.issued_at:
        from crm.services.billing import invoice_due_days

        return invoice.issued_at + datetime.timedelta(days=invoice_due_days(invoice))
    return None


def invoice_status(invoice) -> str:
    code = invoice.status.code if invoice.status else InvoiceStatusCode.ISSUED
    if code == InvoiceStatusCode.PAID:
        return "paid"
    if code == InvoiceStatusCode.CANCELLED:
        return "cancelled"
    if code == InvoiceStatusCode.OVERDUE:
        return "overdue"
    due_date = invoice_due_date(invoice)
    if due_date and due_date < timezone.localdate():
        return "overdue"
    if code == InvoiceStatusCode.PARTIAL or (invoice.amount_paid or 0) > 0:
        return "partially_paid"
    return "issued"


def client_acts_q() -> Q:
    """Акты, которые видит клиент: выставленные и принятые, а также возвращённые им с причиной (ERP хранит возврат
    черновиком с `rejection_reason`; запись прежнего портала с пустым статусом и причиной — тоже возврат). Черновик
    без причины и аннулированный акт — нет."""
    returned = (Q(status__isnull=True) | Q(status__code=ActStatusCode.DRAFT)) & ~Q(rejection_reason="")
    return Q(status__code__in=(ActStatusCode.ISSUED, ActStatusCode.SIGNED)) | returned


def act_status(act) -> str:
    """`SIGNED` — `accepted`; возвращённый клиентом акт ERP хранит черновиком с причиной — `returned`."""
    code = act.status.code if act.status else None
    if code == ActStatusCode.SIGNED:
        return "accepted"
    if code == ActStatusCode.ISSUED:
        return "issued"
    if code in (None, ActStatusCode.DRAFT) and act.rejection_reason:
        return "returned"
    raise ValueError(f"акт в статусе {code} клиенту не показывается")


def act_issued_at(act) -> datetime.datetime:
    """Контракту нужен момент выпуска (date-time): подпись исполнителя, иначе дата выпуска, иначе создание."""
    if act.issuer_signed_at:
        return act.issuer_signed_at
    if act.issued_at:
        return timezone.make_aware(datetime.datetime.combine(act.issued_at, datetime.time.min))
    return act.created_at


# ── Документы ────────────────────────────────────────────────────────────────────────────────────

_DOCUMENT_KINDS = {"contract", "invoice", "act", "quote", "specification", "waybill", "receipt"}


def document_kind(document) -> str:
    template = document.template
    code = template.kind.code.lower() if template and template.kind_id else "other"
    return code if code in _DOCUMENT_KINDS else "other"


def document_size(document) -> int:
    if not document.pdf_file:
        return 0
    try:
        return int(document.pdf_file.size)
    except (OSError, ValueError):
        return 0

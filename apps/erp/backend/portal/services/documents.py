"""Документы клиента в портале (FIX-23, P-12): что клиент видит, как его находит и как получает файл.

`GET /documents` — это проекция уже выпущенных документов ERP, а не таблица «всё, что лежит в хранилище».
Источник у каждого вида свой (у КП, договора, счёта, акта и накладной PDF лежит в самой модели), поэтому
`documents.GeneratedDocument` с ними не связан (QUESTIONS Q-FIX21-1, вариант 2). Новых таблиц нет: идентификатор
документа портала — детерминированная пара «вид источника + id записи» в одном целом числе
(`document_id = pk * 8 + слот вида`), обратимая и стабильная между вызовами.

Правило видимости одно, и им же пользуются список, файл и поля `document_id` / `pdf_document_id` в ответах про КП,
договоры, счета и акты: документ есть у клиента только после выпуска. Черновики, КП до отправки, аннулированные
документы, письма и рапорты («внутренние» `GeneratedDocument`) клиенту не отдаются никогда — ни в списке, ни по id.
"""

from __future__ import annotations

import datetime
import re
from dataclasses import dataclass
from typing import Any, Optional

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext
from documents.models import GeneratedDocument
from portal import projections

from crm.constants import (
    ActStatusCode,
    ContractStatusCode,
    DocumentTemplateKindCode,
    FulfillmentStatusCode,
    GeneratedDocumentStatusCode,
    InvoiceStatusCode,
    QuoteStatusCode,
)
from crm.models import Act, Contract, Fulfillment, Invoice, Quote
from crm.services.documents import quote_pdf_filename
from crm.services.fulfillment import delivery_note_number

#: Слот вида источника в идентификаторе документа (`pk * 8 + слот`). Менять нельзя: id уже у клиентов в ссылках.
SLOT_BY_SOURCE = {"generated": 0, "quote": 1, "contract": 2, "invoice": 3, "act": 4, "waybill": 5}
SOURCE_BY_SLOT = {slot: source for source, slot in SLOT_BY_SOURCE.items()}
_SLOTS = 8

#: Вид документа контракта (`DocumentKind`) по источнику; у `generated` вид берётся из вида шаблона.
KIND_BY_SOURCE = {"quote": "quote", "contract": "contract", "invoice": "invoice", "act": "act", "waybill": "waybill"}

#: Вид шаблона `GeneratedDocument` → вид документа портала. Письмо, рапорт и произвольный документ — внутренние.
KIND_BY_TEMPLATE_KIND = {
    DocumentTemplateKindCode.CONTRACT: "contract",
    DocumentTemplateKindCode.INVOICE: "invoice",
    DocumentTemplateKindCode.ACT: "act",
}

#: `DocumentKind` контракта целиком (его сверяет тест). ERP отдаёт клиентом только виды из `KIND_BY_SOURCE`;
#: по остальным (`specification`, `receipt`, `other`) источника нет и список пуст (QUESTIONS Q-FIX23-3).
DOCUMENT_KINDS = ("quote", "contract", "invoice", "act", "specification", "waybill", "receipt", "other")

#: Статусы «выпущено клиенту». Один набор на фильтр запроса и на проверку одной записи.
#: `EXPIRED` — сохранённый статус КП (сид `core/seeds/sales.py`, его ставит beat `crm.expire_stale_quotes` отправленным КП
#: с прошедшим `valid_until`), не член `QuoteStatusCode`: КП отправлено клиенту и остаётся его документом.
QUOTE_EXPIRED_STATUS = "EXPIRED"
QUOTE_ISSUED = (QuoteStatusCode.SENT, QuoteStatusCode.APPROVED, QuoteStatusCode.REJECTED, QUOTE_EXPIRED_STATUS)
CONTRACT_ISSUED = (
    ContractStatusCode.PENDING_CLIENT,
    ContractStatusCode.PENDING_MANAGER,
    ContractStatusCode.SIGNED,
)
INVOICE_ISSUED = (
    InvoiceStatusCode.ISSUED,
    InvoiceStatusCode.PARTIAL,
    InvoiceStatusCode.PAID,
    InvoiceStatusCode.OVERDUE,
)
ACT_ISSUED = (ActStatusCode.ISSUED, ActStatusCode.SIGNED)
WAYBILL_ISSUED = (
    FulfillmentStatusCode.SHIPPED,
    FulfillmentStatusCode.IN_TRANSIT,
    FulfillmentStatusCode.DELIVERED,
    FulfillmentStatusCode.ACCEPTED,
    FulfillmentStatusCode.DISPUTED,
)

#: Тип задачи рендера `crm.render_document_pdf` по источнику.
RENDER_TYPE = {
    "quote": "quote",
    "contract": "contract",
    "invoice": "invoice",
    "act": "act",
    "waybill": "delivery_note",
    "generated": "generated",
}

#: Сколько секунд клиенту ждать готового PDF (`Retry-After`) и как долго не ставить рендер повторно.
RETRY_AFTER_SECONDS = 2
RENDER_DEBOUNCE_SECONDS = 30


@dataclass(frozen=True)
class PortalDocument:
    """Документ глазами клиента: поля `Document` контракта плюс источник, из которого отдаётся файл."""

    id: int
    kind: str
    source: str
    obj: Any
    number: str
    date: datetime.date
    title: str
    file_name: str
    deal: Any

    @property
    def deal_id(self) -> Optional[int]:
        return self.deal.pk if self.deal is not None else None

    @property
    def file(self):
        """Поле файла источника (`FieldFile`); пустое, пока PDF не отрисован."""
        return self.obj.pdf_file

    @property
    def render_type(self) -> str:
        return RENDER_TYPE[self.source]


# ── Идентификатор ────────────────────────────────────────────────────────────────────────────────


def encode_document_id(source: str, pk: int) -> int:
    return pk * _SLOTS + SLOT_BY_SOURCE[source]


def decode_document_id(document_id: int) -> Optional[tuple[str, int]]:
    """`(источник, pk)` или `None`, если число не выдавалось ни одному документу (слот пуст, pk < 1)."""
    pk, slot = divmod(document_id, _SLOTS)
    source = SOURCE_BY_SLOT.get(slot)
    if source is None or pk < 1:
        return None
    return source, pk


# ── Правило выпуска (для одной записи; тот же набор статусов, что и в запросах ниже) ───────────────


def _status(obj) -> Optional[str]:
    status = getattr(obj, "status", None)
    return status.code if status is not None else None


def is_issued(source: str, obj) -> bool:
    """Выпущена ли запись и значит ли это документ клиента. Единственный ответ на вопрос «видит ли клиент»."""
    code = _status(obj)
    if source == "quote":
        return code in QUOTE_ISSUED
    if source == "contract":
        return code in CONTRACT_ISSUED
    if source == "invoice":
        return code in INVOICE_ISSUED
    if source == "act":
        # Возвращённый клиентом акт ERP хранит черновиком с причиной (портал показывает его как `returned`).
        return code in ACT_ISSUED or (code == ActStatusCode.DRAFT and bool(obj.rejection_reason))
    if source == "waybill":
        return code in WAYBILL_ISSUED
    if source == "generated":
        return code == GeneratedDocumentStatusCode.ISSUED and _generated_kind(obj) is not None
    return False


def document_id_for(source: str, obj) -> Optional[int]:
    """Идентификатор документа записи для полей `document_id` / `pdf_document_id`; `None`, если документа нет."""
    return encode_document_id(source, obj.pk) if is_issued(source, obj) else None


def _generated_kind(document) -> Optional[str]:
    template = document.template
    return KIND_BY_TEMPLATE_KIND.get(template.kind.code) if template and template.kind_id else None


# ── Построение документов ────────────────────────────────────────────────────────────────────────

_UNSAFE_FILENAME = re.compile(r"[^\w\-.]+", flags=re.UNICODE)


def _file_name(number: str, fallback: str) -> str:
    safe = _UNSAFE_FILENAME.sub("_", (number or "").strip()).strip("_")
    return f"{safe or fallback}.pdf"


def _local_date(moment: datetime.datetime) -> datetime.date:
    return timezone.localtime(moment).date()


def _title(label: str, number: str) -> str:
    return f"{label} {number}".strip()


def _quote_document(quote) -> PortalDocument:
    number = projections.quote_number(quote)
    return PortalDocument(
        id=encode_document_id("quote", quote.pk),
        kind="quote",
        source="quote",
        obj=quote,
        number=number,
        date=_local_date(projections.quote_sent_at(quote)),
        title=_title(gettext("Коммерческое предложение"), number),
        file_name=quote_pdf_filename(quote),
        deal=quote.deal,
    )


def _contract_document(contract) -> PortalDocument:
    return PortalDocument(
        id=encode_document_id("contract", contract.pk),
        kind="contract",
        source="contract",
        obj=contract,
        number=contract.number,
        date=_local_date(contract.created_at),
        title=_title(gettext("Договор"), contract.number),
        file_name=_file_name(contract.number, f"contract-{contract.pk}"),
        deal=contract.deal,
    )


def _invoice_document(invoice) -> PortalDocument:
    return PortalDocument(
        id=encode_document_id("invoice", invoice.pk),
        kind="invoice",
        source="invoice",
        obj=invoice,
        number=invoice.number,
        date=invoice.issued_at or _local_date(invoice.created_at),
        title=_title(gettext("Счёт"), invoice.number),
        file_name=_file_name(invoice.number, f"invoice-{invoice.pk}"),
        deal=invoice.deal,
    )


def _act_document(act) -> PortalDocument:
    return PortalDocument(
        id=encode_document_id("act", act.pk),
        kind="act",
        source="act",
        obj=act,
        number=act.number,
        date=act.issued_at or _local_date(act.created_at),
        title=_title(gettext("Акт"), act.number),
        file_name=_file_name(act.number, f"act-{act.pk}"),
        deal=act.deal,
    )


def _waybill_document(fulfillment) -> PortalDocument:
    number = delivery_note_number(fulfillment)
    return PortalDocument(
        id=encode_document_id("waybill", fulfillment.pk),
        kind="waybill",
        source="waybill",
        obj=fulfillment,
        number=number,
        date=_local_date(fulfillment.shipped_at or fulfillment.created_at),
        title=_title(gettext("Накладная"), number),
        file_name=_file_name(number, f"waybill-{fulfillment.pk}"),
        deal=fulfillment.deal,
    )


def _generated_document(document) -> PortalDocument:
    kind = _generated_kind(document)
    label = {"contract": gettext("Договор"), "invoice": gettext("Счёт"), "act": gettext("Акт")}[kind]
    return PortalDocument(
        id=encode_document_id("generated", document.pk),
        kind=kind,
        source="generated",
        obj=document,
        number=document.number,
        date=_local_date(document.issued_at or document.created_at),
        title=document.title or _title(label, document.number),
        file_name=_file_name(document.number, f"document-{document.pk}"),
        deal=document.deal,
    )


_MODEL_BUILDERS = {
    "quote": (Quote, _quote_document),
    "contract": (Contract, _contract_document),
    "invoice": (Invoice, _invoice_document),
    "act": (Act, _act_document),
    "waybill": (Fulfillment, _waybill_document),
}
_ISSUED_STATUSES = {
    "quote": QUOTE_ISSUED,
    "contract": CONTRACT_ISSUED,
    "invoice": INVOICE_ISSUED,
    "waybill": WAYBILL_ISSUED,
}


def _issued_queryset(source: str):
    """Выпущенные записи источника — тот же набор статусов, что и в `is_issued`."""
    model, _build = _MODEL_BUILDERS[source]
    queryset = model.objects.select_related("status", "deal")
    if source == "act":
        returned = Q(status__code=ActStatusCode.DRAFT) & ~Q(rejection_reason="")
        return queryset.filter(Q(status__code__in=ACT_ISSUED) | returned)
    return queryset.filter(status__code__in=_ISSUED_STATUSES[source])


def _generated_queryset(company, deal_id: Optional[int]):
    """Выпущенные `GeneratedDocument` клиентских видов: по сделке компании либо по контакту компании (без сделки)."""
    queryset = GeneratedDocument.objects.filter(
        status__code=GeneratedDocumentStatusCode.ISSUED,
        template__kind__code__in=list(KIND_BY_TEMPLATE_KIND),
    ).select_related("template__kind", "status", "deal")
    if deal_id is not None:
        return queryset.filter(deal_id=deal_id, deal__company=company)
    return queryset.filter(Q(deal__company=company) | Q(deal__isnull=True, contact__company=company))


def client_documents(company, *, kind: Optional[str] = None, deal_id: Optional[int] = None) -> list[PortalDocument]:
    """Документы компании, выпущенные клиенту; новые первыми. Фильтры `kind` и `deal_id` — как в контракте."""
    documents: list[PortalDocument] = []
    for source, (_model, build) in _MODEL_BUILDERS.items():
        if kind not in (None, KIND_BY_SOURCE[source]):
            continue
        queryset = _issued_queryset(source).filter(deal__company=company)
        if deal_id is not None:
            queryset = queryset.filter(deal_id=deal_id)
        documents += [build(obj) for obj in queryset]
    if kind is None or kind in KIND_BY_TEMPLATE_KIND.values():
        generated = [_generated_document(d) for d in _generated_queryset(company, deal_id)]
        documents += [d for d in generated if kind in (None, d.kind)]
    documents.sort(key=lambda d: (d.date, d.id), reverse=True)
    return documents


def find_client_document(company, document_id: int) -> Optional[PortalDocument]:
    """Документ по id, если он выпущен и принадлежит компании; иначе `None` (для API это 404, в том числе для чужого)."""
    decoded = decode_document_id(document_id)
    if decoded is None:
        return None
    source, pk = decoded
    if source == "generated":
        obj, build = _generated_queryset(company, None).filter(pk=pk).first(), _generated_document
    else:
        obj = _issued_queryset(source).filter(pk=pk, deal__company=company).first()
        build = _MODEL_BUILDERS[source][1]
    if obj is None or not is_issued(source, obj):
        return None
    return build(obj)


# ── Файл ─────────────────────────────────────────────────────────────────────────────────────────


def file_size(document: PortalDocument) -> int:
    """Размер готового PDF в байтах; 0, пока файла нет или хранилище его не отдаёт."""
    if not document.file:
        return 0
    try:
        return int(document.file.size)
    except (OSError, ValueError):
        return 0


def open_ready_file(document: PortalDocument):
    """Открытый на чтение PDF или `None`, если он ещё не отрисован (или потерян в хранилище и будет отрисован заново)."""
    if not document.file:
        return None
    try:
        return document.file.open("rb")
    except (OSError, ValueError):
        return None


def enqueue_render(document: PortalDocument) -> bool:
    """Поставить рендер PDF документа в очередь `pdf` (крупный файл в запросе не рисуем — ARCH-03).

    Клиент опрашивает файл каждые `Retry-After` секунд, поэтому повторную постановку в окно
    `RENDER_DEBOUNCE_SECONDS` гасит ключ в кэше: задача идемпотентна, но очередь под опрос не нужна.
    """
    from crm.tasks import render_document_pdf

    key = f"portal:render:{document.render_type}:{document.obj.pk}"
    if not cache.add(key, 1, RENDER_DEBOUNCE_SECONDS):
        return False
    render_document_pdf.delay(document.render_type, document.obj.pk)
    return True


def record_issue(document: PortalDocument, *, contact, session, ip: str) -> None:
    """Запись аудита выдачи файла клиенту: кто (контакт, сессия, IP), что (вид, номер, id) и когда (метка записи)."""
    from crm.models import ActivityLog

    ActivityLog.objects.create(
        action="Клиент скачал документ",
        event_code="document.downloaded_by_client",
        event_params={
            "document_id": document.id,
            "kind": document.kind,
            "number": document.number,
            "contact_id": contact.pk,
            "contact_name": contact.name,
            "session_id": session.pk,
            "ip": ip,
        },
        detail=f"{document.title}: {contact.name}",
        entity_type=document.source,
        entity_id=document.obj.pk,
        company_id=contact.company_id,
        contact_id=contact.pk,
        deal=document.deal,
    )

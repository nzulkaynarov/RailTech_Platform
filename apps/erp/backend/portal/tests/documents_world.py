"""Документы мира сторожа (FIX-23, P-12): выпущенные — с PDF и без, и всё, что клиент видеть не должен.

Подключается из `contract_world` (`build_document_fixtures`): к уже заведённым КП, договорам, счетам, актам и поставкам
добавляются PDF, черновики, внутренние `GeneratedDocument` и документ чужой компании. Ожидания тестов — в словарях:

* `documents`          — ключ → id документа, который ОБЯЗАН быть в `GET /documents` (с источником в имени ключа);
* `ready_documents`    — подмножество `documents`, у которых PDF отрисован (файл отдаётся потоком, остальные — 202);
* `hidden_documents`   — ключ → id, который НЕ должен попасть ни в список, ни в файл (404).
"""

from __future__ import annotations

from django.core.files.base import ContentFile
from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus
from portal.services.documents import encode_document_id

from crm.constants import DealStageCode, InvoiceStatusCode, QuoteStatusCode
from crm.models import Deal, DealStage, Fulfillment, Invoice, InvoiceStatus

PDF = b"%PDF-1.4 fake"


def _status(model, code):
    obj, _ = model.objects.get_or_create(code=code, defaults={"name": code})
    return obj


def _generated(company, contact, deal, *, key, kind_code, status_code, pdf=True):
    kind = _status(DocumentTemplateKind, kind_code)
    template, _ = DocumentTemplate.objects.get_or_create(
        company=company, name=f"Шаблон {kind_code}", defaults={"kind": kind}
    )
    document = GeneratedDocument.objects.create(
        company=company,
        deal=deal,
        contact=contact,
        template=template,
        status=_status(GeneratedDocumentStatus, status_code),
        number=f"DOC-GUARD-{key}",
        title=f"Документ {key}",
        rendered_html="<p>fake</p>",
    )
    if pdf:
        document.pdf_file.save(f"{key}.pdf", ContentFile(PDF), save=True)
    return document


def build_document_fixtures(world: dict) -> dict:
    """Дополняет мир документами; возвращает три словаря ожиданий (см. модуль)."""
    from portal.tests.contract_world import TODAY, make_quote

    company, contact, uzs, main = world["company"], world["contact"], world["uzs"], world["main"]
    documents: dict[str, int] = {}
    ready: dict[str, int] = {}
    hidden: dict[str, int] = {}

    def issued(key, source, obj, *, pdf=False, field="pdf_file"):
        if pdf and not getattr(obj, field):
            getattr(obj, field).save(f"{key}.pdf", ContentFile(PDF), save=True)
        documents[key] = encode_document_id(source, obj.pk)
        if pdf:
            ready[key] = documents[key]

    def concealed(key, source, obj):
        hidden[key] = encode_document_id(source, obj.pk)

    # ── Выпущенные: у каждого вида — с готовым PDF и без него ──────────────────────────────────
    for key, quote in world["quotes"].items():
        issued(f"quote_{key}", "quote", quote, pdf=key in ("sent", "accepted", "expired_status"))
    for key, contract in world["contracts"].items():
        if key in ("draft", "cancelled"):
            concealed(f"contract_{key}", "contract", contract)
        else:
            issued(f"contract_{key}", "contract", contract, pdf=key == "signed")
    for key, invoice in world["invoices"].items():
        if key in ("draft", "not_issued"):  # черновик и счёт без срока и даты выставления — как в GET /invoices
            concealed(f"invoice_{key}", "invoice", invoice)
        else:
            issued(f"invoice_{key}", "invoice", invoice, pdf=key in ("paid", "issued"))
    for key, act in world["acts"].items():
        if key in ("cancelled", "draft"):
            concealed(f"act_{key}", "act", act)
        else:
            issued(f"act_{key}", "act", act, pdf=key == "accepted")
    # Скан подписанного акта — документ, заведённый приёмкой (`portal.services.act_scan.attach_scan_document`): файл общий
    # с `Act.signed_file`, метка `values.source == "portal_scan"`.
    accepted = world["acts"]["accepted"]
    scan = _generated(company, contact, main, key="scan", kind_code="ACT", status_code="ISSUED", pdf=False)
    GeneratedDocument.objects.filter(pk=scan.pk).update(
        number=f"SCAN-{accepted.number}",
        title=f"Скан подписанного акта {accepted.number}",
        values={"act_id": accepted.pk, "source": "portal_scan"},
        pdf_file=accepted.signed_file.name,
    )
    scan.refresh_from_db()
    issued("act_scan", "generated", scan)
    ready["act_scan"] = documents["act_scan"]
    world["scan_document"] = scan
    for key, fulfillment in world["deliveries"].items():
        issued(f"quote_delivery_{key}", "quote", fulfillment.deal.quotes.get())  # подтверждённое КП сделки поставки
        if key == "assembling":
            concealed("waybill_assembling", "waybill", fulfillment)
        else:
            Fulfillment.objects.filter(pk=fulfillment.pk).update(note_number=f"DN-GUARD-{key}")
            fulfillment.refresh_from_db()
            issued(f"waybill_{key}", "waybill", fulfillment, pdf=key == "shipped")

    # ── Выпущенные GeneratedDocument клиентских видов: по сделке, без готового PDF, без сделки (по контакту) ──
    gen_contract = _generated(company, contact, main, key="gc", kind_code="CONTRACT", status_code="ISSUED")
    issued("generated_contract", "generated", gen_contract, pdf=True)
    gen_pending = _generated(company, contact, main, key="gp", kind_code="INVOICE", status_code="ISSUED", pdf=False)
    issued("generated_pending", "generated", gen_pending)
    gen_no_deal = _generated(company, contact, None, key="gnd", kind_code="ACT", status_code="ISSUED", pdf=False)
    issued("generated_no_deal", "generated", gen_no_deal)

    # ── Черновики и внутренние: клиент не видит никогда ─────────────────────────────────────────
    internal_deal = Deal.objects.create(
        company=company, contact=contact, title="Внутренний расчёт", stage=_status(DealStage, DealStageCode.CALCULATING)
    )
    for version, (key, code) in enumerate(
        (
            ("draft", QuoteStatusCode.DRAFT),
            ("pending_approval", QuoteStatusCode.PENDING_APPROVAL),
            ("ready_to_send", QuoteStatusCode.READY_TO_SEND),
        ),
        start=1,
    ):
        quote = make_quote(internal_deal, version, code, uzs=uzs, sent=False, items=False)
        quote.pdf_file.save(f"quote-{key}.pdf", ContentFile(PDF), save=True)  # PDF есть, но КП не отправлено
        concealed(f"quote_{key}", "quote", quote)
    # КП до отправки и «отправленное» без публичной ссылки (FIX-22): PDF у них может быть, документа — нет.
    for key, quote in world["hidden_quotes"].items():
        quote.pdf_file.save(f"quote-hidden-{key}.pdf", ContentFile(PDF), save=True)
        concealed(f"quote_hidden_{key}", "quote", quote)
    concealed("waybill_bare", "waybill", world["bare_fulfillment"])
    concealed(
        "generated_letter",
        "generated",
        _generated(company, contact, main, key="gl", kind_code="LETTER", status_code="ISSUED"),
    )
    concealed(
        "generated_report",
        "generated",
        _generated(company, contact, main, key="gr", kind_code="REPORT", status_code="ISSUED"),
    )
    concealed(
        "generated_custom",
        "generated",
        _generated(company, contact, None, key="gcu", kind_code="CUSTOM", status_code="ISSUED"),
    )
    concealed(
        "generated_draft",
        "generated",
        _generated(company, contact, main, key="gdr", kind_code="CONTRACT", status_code="DRAFT"),
    )
    concealed(
        "generated_cancelled",
        "generated",
        _generated(company, contact, main, key="gca", kind_code="INVOICE", status_code="CANCELLED"),
    )

    # ── Чужая компания: выпущенный документ есть, у клиента А его нет ──────────────────────────
    other = world["other"]
    other_invoice = Invoice.objects.create(
        deal=other["deal"],
        number="INV-GUARD-other",
        status=_status(InvoiceStatus, InvoiceStatusCode.ISSUED),
        issued_at=TODAY,
    )
    other_invoice.pdf_file.save("inv-other.pdf", ContentFile(PDF), save=True)
    concealed("other_company_quote", "quote", other["quote"])
    concealed("other_company_invoice", "invoice", other_invoice)
    return {
        "documents": documents,
        "ready_documents": ready,
        "hidden_documents": hidden,
        "internal_deal": internal_deal,
    }

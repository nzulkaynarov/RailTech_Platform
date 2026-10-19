"""Мир фикстур сторожа контракта портала (FIX-21): сущности клиента во ВСЕХ статусах, которые портал умеет отдавать.

Фикстура `contract_world` строит данные клиента А (и одну сделку клиента Б для негативных проверок). Список статусов
здесь — это «что мы заводим», а какие статусы портал обязан показать, сторож берёт из схем контракта
(`DeliveryStatus`, `InvoiceStatus` …): он сверяет, что каждое значение, достижимое из модели, встретилось в ответе.
"""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal

import pytest
from django.core.files.base import ContentFile
from django.utils import timezone
from documents.models import DocumentTemplate, DocumentTemplateKind, GeneratedDocument, GeneratedDocumentStatus
from portal.models import MagicLinkToken, PortalRequestLine, PortalUpload
from portal.services.tokens import hash_token

from catalog.models import Category, Product, ProductStatus
from core.models import Currency
from crm.constants import (
    ActStatusCode,
    ContractStatusCode,
    DealStageCode,
    FulfillmentStatusCode,
    InvoiceStatusCode,
    QuoteStatusCode,
)
from crm.models import (
    Act,
    ActivityLog,
    ActStatus,
    Contract,
    ContractStatus,
    Deal,
    DealStage,
    Fulfillment,
    FulfillmentStatus,
    Invoice,
    InvoiceStatus,
    Quote,
    QuoteItem,
    QuoteStatus,
)
from master_data.models import UnitOfMeasure

TODAY = datetime.date.today()
MAGIC_TOKEN = "magic-token-for-contract-guard-0001"


def _status(model, code, name=None):
    obj, _ = model.objects.get_or_create(code=code, defaults={"name": name or code})
    return obj


def _stage(code):
    return _status(DealStage, code)


def make_quote(
    deal, version, status_code, *, uzs, sent=True, valid_until=None, viewed=False, items=True, product=None, **fields
):
    quote = Quote.objects.create(
        deal=deal,
        version=version,
        status=_status(QuoteStatus, status_code),
        quote_currency=uzs,
        valid_until=valid_until,
        **fields,
    )
    if sent:
        quote.number = f"КП-2026-{deal.pk:03d}-{version}"
        quote.public_access_token = uuid.uuid4().hex
        quote.frozen_at = timezone.now() - datetime.timedelta(days=2)
        if viewed:
            quote.first_viewed_at = timezone.now() - datetime.timedelta(days=1)
        quote.save()
    if items:
        add_quote_items(quote, product)
        quote.refresh_from_db()
    return quote


def add_quote_items(quote, product=None):
    """Раздел → позиция из каталога → позиция по сырому названию → заметка; опциональная позиция вне итогов."""
    QuoteItem.objects.create(quote=quote, display_type="SECTION", imported_raw_name="Трубы", position=1)
    QuoteItem.objects.create(
        quote=quote,
        display_type="ITEM",
        product=product,
        imported_raw_name="Труба 89х4 ст20",
        quantity=150,
        unit="м",
        frozen_base_price=Decimal("500000"),
        margin_percent=Decimal("10"),
        lead_time_days=14,
        position=2,
    )
    QuoteItem.objects.create(
        quote=quote,
        display_type="ITEM",
        imported_raw_name="Отвод 89х4",
        quantity=10,
        unit="шт",
        frozen_base_price=Decimal("120000"),
        margin_percent=Decimal("0"),
        position=3,
    )
    QuoteItem.objects.create(
        quote=quote, display_type="NOTE", imported_raw_name="Цены действительны 14 дней", position=4
    )
    QuoteItem.objects.create(
        quote=quote,
        display_type="ITEM",
        imported_raw_name="Опциональный монтаж",
        quantity=1,
        unit="усл.",
        frozen_base_price=Decimal("900000"),
        is_optional=True,
        position=5,
    )


@pytest.fixture
def contract_world(db, client_company, other_company, client_contact, other_contact, seller_company, client_session):
    uzs, _ = Currency.objects.get_or_create(code="UZS", defaults={"name": "Узбекский сум", "symbol": "so'm"})
    unit, _ = UnitOfMeasure.objects.get_or_create(code="796", defaults={"name": "шт"})
    category = Category.objects.create(name="Трубы и фитинги")
    product = Product.objects.create(
        name="Труба 89х4 ст20",
        sku="PIPE-89-4",
        category=category,
        uom=unit,
        status=_status(ProductStatus, "PUBLISHED", "Опубликован"),
        list_price=Decimal("450000"),
        list_price_currency=uzs,
        price_visibility="cabinet",
    )

    world: dict = {"uzs": uzs, "product": product, "company": client_company, "contact": client_contact}

    # ── Запросы: четыре статуса и три источника ────────────────────────────────────────────────
    new_deal = Deal.objects.create(
        company=client_company, contact=client_contact, title="Новый запрос", stage=_stage(DealStageCode.DRAFT)
    )
    PortalRequestLine.objects.create(deal=new_deal, text="Труба 89х4", quantity=Decimal("150"), unit="м", sort_order=1)
    PortalRequestLine.objects.create(deal=new_deal, text="Что-нибудь без количества", sort_order=2)
    PortalUpload.objects.create(
        company=client_company,
        uploaded_by=client_contact,
        deal=new_deal,
        name="specification.pdf",
        file=ContentFile(b"%PDF-1.4 fake", name="specification.pdf"),
        size_bytes=13,
        content_type="application/pdf",
    )
    ActivityLog.objects.create(
        deal=new_deal, action="Создан запрос", event_code="deal.created", event_params={"source": "cabinet"}
    )
    in_progress = Deal.objects.create(
        company=client_company, contact=client_contact, title="", stage=_stage(DealStageCode.SOURCING)
    )
    ActivityLog.objects.create(
        deal=in_progress, action="Сделка создана", event_code="deal.created", event_params={"actor_email": "s@e.uz"}
    )
    closed = Deal.objects.create(
        company=client_company, contact=client_contact, title="Закрытая", stage=_stage(DealStageCode.CLOSED_WON)
    )
    main = Deal.objects.create(
        company=client_company, contact=client_contact, title="Поставка труб", stage=_stage(DealStageCode.QUOTE_SENT)
    )
    world.update(new_deal=new_deal, in_progress=in_progress, closed=closed, main=main)

    # ── КП: sent / viewed / accepted / rejected / expired ────────────────────────────────────
    past = TODAY - datetime.timedelta(days=3)
    future = TODAY + datetime.timedelta(days=10)
    # Позиция из каталога (`product`) — путь, на котором `GET /quotes/{id}` падал 500 (P-7): единица берётся из карточки.
    quotes = {
        "sent": make_quote(main, 1, QuoteStatusCode.SENT, uzs=uzs, valid_until=future, product=product),
        "viewed": make_quote(main, 2, QuoteStatusCode.SENT, uzs=uzs, valid_until=future, viewed=True, product=product),
        "accepted": make_quote(main, 3, QuoteStatusCode.APPROVED, uzs=uzs, product=product),
        "rejected": make_quote(main, 4, QuoteStatusCode.REJECTED, uzs=uzs, product=product),
        "expired": make_quote(main, 5, QuoteStatusCode.SENT, uzs=uzs, valid_until=past, product=product),
        # Статус EXPIRED ставит ночная задача `crm.expire_stale_quotes`: КП не должно пропадать у клиента на следующий день.
        "expired_status": make_quote(main, 11, "EXPIRED", uzs=uzs, valid_until=past, product=product),
    }
    # КП до отправки клиенту не видны вовсе (404): у них нет публичной ссылки, а `Quote.public_url` в контракте обязателен.
    hidden_quotes = {
        status_code.lower(): make_quote(main, 6 + number, status_code, uzs=uzs, sent=False, product=product)
        for number, status_code in enumerate(
            (
                QuoteStatusCode.DRAFT,
                QuoteStatusCode.PENDING_TRADE_REVIEW,
                QuoteStatusCode.PENDING_APPROVAL,
                QuoteStatusCode.READY_TO_SEND,
            )
        )
    }
    # Отправленное КП без публичной ссылки — аномалия данных (ссылка рождается вместе со статусом SENT): тоже скрыто.
    hidden_quotes["sent_without_link"] = make_quote(main, 10, QuoteStatusCode.SENT, uzs=uzs, sent=False)
    world["hidden_quotes"] = hidden_quotes
    ActivityLog.objects.create(
        deal=main,
        action="КП отклонено клиентом",
        event_code="quote.rejected",
        entity_type="quote",
        entity_id=quotes["rejected"].pk,
        event_params={"version": 4, "reason": "Дорого"},
    )
    # Сквозные суммы без декларации: сумма уже посчитана движком; добавляем «статьи расходов» документа.
    Quote.objects.filter(pk=quotes["sent"].pk).update(charges_total=Decimal("50000.00"))
    world["quotes"] = quotes

    # ── Договоры: sent / signed_by_client / signed_by_company / signed / cancelled (+ черновик) ─
    contracts = {}
    now = timezone.now()
    for key, status_code, extra in (
        ("sent", ContractStatusCode.PENDING_CLIENT, {}),
        ("signed_by_client", ContractStatusCode.PENDING_MANAGER, {"client_signed_at": now}),
        ("signed_by_company", ContractStatusCode.PENDING_CLIENT, {"manager_signed_at": now}),
        ("signed", ContractStatusCode.SIGNED, {"client_signed_at": now, "manager_signed_at": now}),
        ("cancelled", ContractStatusCode.CANCELLED, {}),
        ("draft", ContractStatusCode.DRAFT, {}),
    ):
        contracts[key] = Contract.objects.create(
            deal=main,
            quote=quotes["accepted"],
            number=f"CT-GUARD-{key}",
            status=_status(ContractStatus, status_code),
            total_amount=Decimal("84000000"),
            currency=uzs,
            **extra,
        )
    world["contracts"] = contracts

    # ── Счета: issued / partially_paid / paid / overdue / cancelled ────────────────────────────
    invoices = {}
    for key, status_code, due, paid in (
        ("issued", InvoiceStatusCode.ISSUED, future, "0"),
        ("partially_paid", InvoiceStatusCode.PARTIAL, future, "1000000"),
        ("paid", InvoiceStatusCode.PAID, past, "84000000"),
        ("overdue", InvoiceStatusCode.OVERDUE, past, "0"),
        ("cancelled", InvoiceStatusCode.CANCELLED, future, "0"),
        ("no_due_date", InvoiceStatusCode.ISSUED, None, "0"),  # срок вычисляется правилом выставления (+14 дней)
        ("draft", InvoiceStatusCode.DRAFT, future, "0"),
        ("not_issued", InvoiceStatusCode.ISSUED, None, "0"),  # ни срока, ни даты выставления — клиенту не показывается
    ):
        invoices[key] = Invoice.objects.create(
            deal=main,
            contract=contracts["signed"],
            number=f"INV-GUARD-{key}",
            status=_status(InvoiceStatus, status_code),
            due_date=due,
            issued_at=None if key == "not_issued" else TODAY,
            total_incl_vat=Decimal("84000000"),
            amount_paid=Decimal(paid),
            currency=uzs,
        )
    world["invoices"] = invoices

    # ── Акты: issued / accepted (со сканом) / returned (+ аннулированный) ─────────────────────
    acts = {}
    for key, status_code, extra in (
        ("issued", ActStatusCode.ISSUED, {}),
        ("accepted", ActStatusCode.SIGNED, {"signed_at": now, "acceptor_signed_at": now}),
        ("returned", ActStatusCode.DRAFT, {"rejection_reason": "Не совпадает количество"}),
        ("cancelled", ActStatusCode.CANCELLED, {}),
        ("draft", ActStatusCode.DRAFT, {}),  # черновик без причины возврата — клиенту не показывается
    ):
        acts[key] = Act.objects.create(
            deal=main,
            contract=contracts["signed"],
            invoice=invoices["paid"],
            number=f"ACT-GUARD-{key}",
            status=_status(ActStatus, status_code),
            issued_at=TODAY,
            total_amount=Decimal("84000000"),
            **extra,
        )
    acts["accepted"].signed_file.save("scan.pdf", ContentFile(b"%PDF-1.4 scan"), save=True)
    world["acts"] = acts

    # ── Поставки: по сделке на статус исполнения; строки — из подтверждённого КП ──────────────
    deliveries = {}
    for key, code in (
        ("assembling", FulfillmentStatusCode.PENDING),
        ("shipped", FulfillmentStatusCode.SHIPPED),
        ("in_transit", FulfillmentStatusCode.IN_TRANSIT),
        ("delivered", FulfillmentStatusCode.DELIVERED),
        ("accepted", FulfillmentStatusCode.ACCEPTED),
        ("disputed", FulfillmentStatusCode.DISPUTED),
    ):
        deal = Deal.objects.create(
            company=client_company, contact=client_contact, title=f"Поставка {key}", stage=_stage("CONTRACT_SIGNED")
        )
        make_quote(deal, 1, QuoteStatusCode.APPROVED, uzs=uzs)
        extra = {}
        if key != "assembling":
            extra.update(shipped_at=now, tracking_number="TRK-0001", expected_delivery_date=future)
        if key == "accepted":
            extra.update(accepted_at=now, delivered_at=now)
        if key == "delivered":
            extra.update(delivered_at=now)
        deliveries[key] = Fulfillment.objects.create(deal=deal, status=_status(FulfillmentStatus, code), **extra)
    world["deliveries"] = deliveries
    # Сделка без подтверждённого КП, но с исполнением: строк поставки нет, выдумывать нечего.
    bare = Deal.objects.create(
        company=client_company, contact=client_contact, title="Без КП", stage=_stage("CONTRACT_SIGNED")
    )
    Fulfillment.objects.create(deal=bare, status=_status(FulfillmentStatus, FulfillmentStatusCode.PENDING))

    # ── Документы: выпущенные разных видов; сделка у одного отсутствует ───────────────────────
    issued = _status(GeneratedDocumentStatus, "ISSUED", "Выпущен")
    documents = {}
    for key, kind_code, deal in (
        ("contract", "CONTRACT", main),
        ("invoice", "INVOICE", main),
        ("act", "ACT", main),
        ("letter", "LETTER", main),
        ("pending", "LETTER", main),  # PDF ещё не отрисован
        ("no_deal", "LETTER", None),
    ):
        kind = _status(DocumentTemplateKind, kind_code)
        template, _ = DocumentTemplate.objects.get_or_create(
            company=client_company, name=f"Шаблон {kind_code}", defaults={"kind": kind}
        )
        document = GeneratedDocument.objects.create(
            company=client_company,
            deal=deal,
            template=template,
            status=issued,
            number=f"DOC-GUARD-{key}",
            title=f"Документ {key}",
            rendered_html="<p>fake</p>",
        )
        if key not in ("pending", "no_deal"):
            document.pdf_file.save(f"{key}.pdf", ContentFile(b"%PDF-1.4 fake"), save=True)
        documents[key] = document
    # Скан подписанного акта — документ, заведённый приёмкой (`portal.services.act_scan.attach_scan_document`).
    scan = GeneratedDocument.objects.create(
        company=client_company,
        deal=main,
        template=DocumentTemplate.objects.get(company=client_company, name="Шаблон ACT"),
        status=issued,
        number=f"SCAN-{acts['accepted'].number}",
        title=f"Скан подписанного акта {acts['accepted'].number}",
        rendered_html="",
    )
    GeneratedDocument.objects.filter(pk=scan.pk).update(pdf_file=acts["accepted"].signed_file.name)
    documents["scan"] = scan
    world["documents"] = documents

    # ── Токен входа (для GET /auth/magic/{token}) ───────────────────────────────────────────────
    MagicLinkToken.objects.create(
        token_hash=hash_token(MAGIC_TOKEN),
        contact=client_contact,
        expires_at=timezone.now() + datetime.timedelta(minutes=15),
    )
    world["magic_token"] = MAGIC_TOKEN

    # ── Чужая компания: для негативных проверок ───────────────────────────────────────────────
    other_deal = Deal.objects.create(
        company=other_company, contact=other_contact, title="Чужая сделка", stage=_stage(DealStageCode.QUOTE_SENT)
    )
    world["other"] = {
        "deal": other_deal,
        "quote": make_quote(other_deal, 1, QuoteStatusCode.SENT, uzs=uzs),
    }
    return world

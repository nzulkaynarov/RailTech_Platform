from typing import Optional, Tuple

from django.db import IntegrityError, transaction

from accounts.models import CustomUser

from ..constants import DEFAULT_INVOICE_DUE_DAYS, ActStatusCode, ContractStatusCode, InvoiceStatusCode
from ..models import ActivityLog
from ._params import PaymentData

# ──────────────────────────────────────────────────────────────────────────
# Invoices, Payments, Acts
# ──────────────────────────────────────────────────────────────────────────


def _next_invoice_number(seller_company=None) -> str:
    # Race-safe per-(company, year) counter (was count()+1 → duplicate-number 500 under
    # load). Carries the seller company so the invoice gets THEIR prefix + counter.
    from .numbering import next_document_number

    return next_document_number("INV", "INV", company=seller_company)


def _next_receipt_number(seller_company=None) -> str:
    from .numbering import next_document_number

    return next_document_number("RCP", "RCP", company=seller_company)


def _next_act_number(seller_company=None) -> str:
    from .numbering import next_document_number

    return next_document_number("ACT", "ACT", company=seller_company)


def _istatus(code: str):
    """Resolve an InvoiceStatus lookup by code (F5.4 — status is a FK now)."""
    from ..models import InvoiceStatus

    return InvoiceStatus.objects.get(code=code)


def _astatus(code: str):
    """Resolve an ActStatus lookup by code (F5.4 — status is a FK now)."""
    from ..models import ActStatus

    return ActStatus.objects.get(code=code)


@transaction.atomic
def generate_invoice_from_contract(
    contract_id: int,
    actor: Optional[CustomUser] = None,
    due_days: int = DEFAULT_INVOICE_DUE_DAYS,
) -> Tuple[Optional["Invoice"], Optional[str]]:  # noqa: F821
    from datetime import timedelta

    from django.utils import timezone

    from accounts.services import is_seller

    from ..models import Contract, Invoice, InvoiceItem

    # Issuing the invoice is a seller-side action.
    if actor is not None and not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    try:
        contract = Contract.objects.select_related("quote__deal", "quote__quote_currency").get(pk=contract_id)
    except Contract.DoesNotExist:
        return None, "NOT_FOUND"

    if contract.status_code != ContractStatusCode.SIGNED:
        return None, "INVOICE_REQUIRES_SIGNED_CONTRACT"

    # Idempotency: one signed contract yields one LIVE invoice. Re-issuing would
    # double-count receivables. Return the existing invoice instead — but a CANCELLED
    # invoice is dead: excluding it lets the seller re-invoice a signed contract after a
    # cancellation (otherwise the договор dead-ends). Mirrors the auto-path guard in
    # tasks.auto_invoice_on_closed_won so the automation never re-surfaces a cancelled one.
    existing_invoice = (
        Invoice.objects.filter(contract=contract).exclude(status__code=InvoiceStatusCode.CANCELLED).first()
    )
    if existing_invoice is not None:
        return existing_invoice, None

    quote = contract.quote
    # Seller company = the КП author's owning company → its prefix + per-company counter.
    from .quotes import _quote_seller_company

    seller_company = _quote_seller_company(quote)
    # ONLY billable lines become InvoiceItems: SECTION/NOTE carry no price and optional ITEMs are
    # quoted OUTSIDE the КП totals. Billing every row (the old .items.all()) put optional/section/
    # note lines on the invoice so Σ(InvoiceItem.line_total) overshot Invoice.total (which mirrors
    # the header total that already excludes them) — the invoice stopped adding up.
    billable_items = list(quote.items.billable().select_related("product"))
    # Wave C: an invoice is BORN as a DRAFT (ERP canon — Odoo draft→posted). It carries no
    # issue date and no PDF yet; the seller reviews it (due_date / notes editable while DRAFT)
    # and then explicitly `issue_invoice` → ISSUED (renders the PDF, notifies the buyer).
    invoice = Invoice.objects.create(
        deal=contract.deal,
        contract=contract,
        number=_next_invoice_number(seller_company),
        status=_istatus(InvoiceStatusCode.DRAFT),
        issued_at=None,
        due_date=(timezone.now() + timedelta(days=due_days)).date(),
        subtotal_excl_vat=quote.subtotal_excl_vat,
        vat_amount=quote.vat_amount,
        total_incl_vat=quote.total_incl_vat,
        # B1: the amounts above are copied verbatim from the quote header, which the calculation
        # engine computes and stores in the PRESENTATION currency (Quote.quote_currency, UZS by
        # business rule). The old probe took the first billable line's frozen_currency — that is
        # the COST currency (supplier price, often USD/EUR for imported rail equipment), so an
        # invoice for 13 349 617.98 UZS printed "13 349 617.98 USD". Nullable by design: the PDF
        # template falls back to UZS, matching the engine's canonical currency.
        currency=quote.quote_currency,
        created_by=actor,
    )

    for qi in billable_items:
        InvoiceItem.objects.create(
            invoice=invoice,
            description=(qi.product.name if qi.product else qi.imported_raw_name) or "Позиция",
            quantity=qi.quantity,
            unit_price_excl_vat=qi.final_price_excl_vat,
            line_total_excl_vat=(qi.final_price_excl_vat * qi.quantity),
            source_quote_item=qi,
        )

    # No PDF at DRAFT — the render happens on `issue_invoice` (a draft has no legal PDF yet).
    ActivityLog.objects.create(
        action="Счёт создан (черновик)",
        detail=f"Счёт {invoice.number} по сделке #{invoice.deal_id}",
        event_code="invoice.created",
        event_params={"number": invoice.number, "deal_id": invoice.deal_id},
        user=actor,
        level="INFO",
        deal=invoice.deal,
        company_id=invoice.deal.company_id,
    )
    return invoice, None


def invoice_due_days(invoice) -> int:
    """Срок оплаты в днях для ЭТОГО счёта: настройка компании-продавца, иначе умолчание.

    Раньше 14 дней были зашиты числом. Настройка машинная и отдельная от текстовых «Условий
    оплаты» бланка КП («100% предоплата»): из текста дату посчитать нельзя.
    """
    from ..constants import DEFAULT_INVOICE_DUE_DAYS

    supplier = _invoice_seller_company(invoice)
    if supplier is None:
        return DEFAULT_INVOICE_DUE_DAYS
    return supplier.settings.payment_terms_days or DEFAULT_INVOICE_DUE_DAYS


def _invoice_seller_company(invoice):
    """Resolve the REAL seller (supplier) that a legal invoice must name — never a platform
    identity (Rule 1/2). A contract-based invoice resolves via contract→КП. A MANUAL invoice
    (Wave G, contract=None) loses that link, so fall back, in order, to:
      (1) a source КП carried on its items (built «из активного КП»),
      (2) the own company — the seller of every deal (core.tenant.own_company_id).
    Returns None only when no seller is derivable — the template then shows «—», not a fake ИНН.
    """
    from accounts.models import Company

    from .quotes import _quote_seller_company

    quote = invoice.contract.quote if (invoice.contract_id and invoice.contract.quote_id) else None
    if quote is None:
        item = invoice.items.filter(source_quote_item__isnull=False).select_related("source_quote_item__quote").first()
        if item and item.source_quote_item and item.source_quote_item.quote_id:
            quote = item.source_quote_item.quote
    supplier = _quote_seller_company(quote) if quote else None
    if supplier is None:
        # Pure-manual счёт without a source КП: the seller is the own company (BUSINESS §3.3).
        from core.tenant import own_company_id

        company_id = own_company_id()
        if company_id:
            supplier = Company.objects.filter(pk=company_id).first()
    return supplier


def _render_invoice_pdf(invoice) -> None:
    from io import BytesIO

    from django.core.files.base import ContentFile
    from django.template.loader import render_to_string
    from weasyprint import HTML

    from .documents import brand_context_for_pdf, document_brand_context, document_totals

    supplier = _invoice_seller_company(invoice)
    invoice_brand = document_brand_context(supplier)
    # O3: выставленный счёт печатает ЗАМОРОЖЕННЫЕ реквизиты (снимок момента выставления),
    # а не сегодняшние из профиля — как и замороженный шаблон рядом (E3). Черновик следует
    # за живым профилем: пока счёт не выставлен, продавец как раз и правит реквизиты.
    if invoice.frozen_bank_details:
        profile = invoice_brand.get("seller_profile")
        if profile is not None:
            profile.bank_details = invoice.frozen_bank_details

    # D1: shared 3-line VAT bridge (+ paid/balance rows). Same block as КП/договор/акт.
    ccy = invoice.currency.code if invoice.currency_id else "UZS"
    totals = document_totals(
        ccy=ccy,
        subtotal=invoice.subtotal_excl_vat,
        vat_amount=invoice.vat_amount,
        total=invoice.total_incl_vat,
        amount_paid=invoice.amount_paid,
        balance_due=invoice.balance_due,
    )
    items = invoice.items.select_related("source_quote_item").all()

    # E1b: шаблон компании (или платформенный образец) — тем же механизмом, что акт. Компания
    # правит ТЕКСТ, структурные блоки собирает сервер. Шаблона нет → прежний путь из кода.
    # E3: выставленный счёт печатает ЗАМОРОЖЕННУЮ при выставлении редакцию — живой шаблон
    # читается только пока счёт черновик (или для документов, выпущенных до E3).
    from .document_blocks import company_template_for, render_invoice_body

    frozen_body = invoice.frozen_template_body
    invoice_template = None if frozen_body else company_template_for(supplier, "INVOICE")
    if frozen_body or invoice_template is not None:
        html_string = render_to_string(
            "crm/invoice_pdf_templated.html",
            {
                "invoice": invoice,
                "company": invoice.deal.company,
                "contact": invoice.deal.contact,
                "body_html": render_invoice_body(
                    invoice,
                    items,
                    totals,
                    ccy,
                    invoice_template,
                    seller=invoice_brand.get("seller"),
                    seller_profile=invoice_brand.get("seller_profile"),
                    body_html=frozen_body or None,
                ),
                **brand_context_for_pdf(invoice_brand),
            },
        )
        buf = BytesIO()
        HTML(string=html_string).write_pdf(buf)
        invoice.pdf_file.save(f"Invoice_{invoice.number}.pdf", ContentFile(buf.getvalue()), save=True)
        return

    html_string = render_to_string(
        "crm/invoice_pdf.html",
        {
            "invoice": invoice,
            "items": items,
            "company": invoice.deal.company,
            "totals": totals,
            **brand_context_for_pdf(invoice_brand),
        },
    )
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    invoice.pdf_file.save(f"Invoice_{invoice.number}.pdf", ContentFile(buf.getvalue()), save=True)


@transaction.atomic
def record_payment(
    payment_data_or_invoice_id,
    actor: CustomUser,
    amount=None,
    paid_at=None,
    method: str = "BANK_TRANSFER",
    reference: str = "",
    proof_file=None,
    manual: bool = True,
) -> Tuple[Optional[object], Optional[str]]:
    """Record payment against an invoice.

    Accepts either a PaymentData dataclass or positional/keyword args for
    backwards compatibility. New callers should prefer PaymentData.

    NOTE: manual=True marks the record as hand-entered (no payment-provider webhook).
    Logged with [MANUAL_MODE] tag in ActivityLog -- needed for later reconciliation
    once Click/Payme/Stripe webhooks replace the manual flow. See memory
    `tech_debt_payment_esign.md`.
    """
    # Unpack PaymentData if provided
    if isinstance(payment_data_or_invoice_id, PaymentData):
        pd = payment_data_or_invoice_id
        invoice_id = pd.invoice_id
        amount = pd.amount
        paid_at = pd.paid_at
        method = pd.method
        reference = pd.reference
        proof_file = pd.proof_file
        manual = pd.manual
    else:
        invoice_id = payment_data_or_invoice_id

    from decimal import Decimal as D

    from ..models import Invoice, Payment

    try:
        invoice = Invoice.objects.select_for_update().select_related("deal").get(pk=invoice_id)
    except Invoice.DoesNotExist:
        return None, "NOT_FOUND"
    # Оплату фиксирует бэк-офис: сотрудник своей компании с правом роли `finance.payment`
    # (M1-ERP-05); администратор — всегда. Участников компаний-клиентов в ERP нет (FIX-13).
    if not getattr(actor, "is_superuser", False):
        from accounts.services import member_has_permission, primary_seller_company_id

        own_company_id = primary_seller_company_id(actor)
        if own_company_id is None:
            return None, "MEMBER_REQUIRED_FOR_ACTION"
        if not member_has_permission(actor, own_company_id, "finance.payment"):
            return None, "ROLE_NOT_PERMITTED"
    if invoice.status_code in {InvoiceStatusCode.CANCELLED}:
        return None, "INVOICE_CANCELLED"
    # A DRAFT invoice was never issued — it has no issue date / legal PDF. Paying it would mint a
    # "zombie" PAID invoice that can never be issued (ALWAYS_ISSUED) nor cancelled (CANNOT_CANCEL_PAID),
    # and an act could be generated against a never-issued счёт. Payment is only against a live
    # receivable: ISSUED / PARTIAL / OVERDUE.
    if invoice.status_code == InvoiceStatusCode.DRAFT:
        return None, "INVOICE_NOT_ISSUED"
    # A fully-paid invoice takes no further money (no over-payment).
    if invoice.status_code == InvoiceStatusCode.PAID:
        return None, "INVOICE_ALREADY_PAID"
    amount_d = D(str(amount))
    if amount_d <= 0:
        return None, "PAYMENT_AMOUNT_MUST_BE_POSITIVE"
    # Сумма не больше ОСТАТКА, а не только «счёт ещё не закрыт».
    #
    # Проверка выше отбивала лишь ВТОРОЙ платёж по уже закрытому счёту, а первый платёж любого
    # размера проходил: `amount_paid` уходил выше суммы счёта, `balance_due` становился
    # отрицательным, счёт получал статус PAID — и на несуществующие деньги выпускалась квитанция,
    # печатный артефакт. Единственная защита жила в браузере (`RecordPaymentDialog`), то есть её
    # не было: тем же токеном покупателя curl клал в реестр 99 999 999 999 при счёте на 73 472 000
    # (прогон 20-08). Дефект жил с первой реализации биллинга, с 2026-04-18.
    #
    # Денежные эталоны здесь единодушны: Stripe, Odoo и QuickBooks не дают записать поступление
    # больше остатка — излишек оформляется ОТДЕЛЬНОЙ сущностью (аванс, кредит-нота), а не молча
    # уходит в минус по счёту. Такой сущности у нас нет, поэтому и приём сверх остатка запрещаем.
    balance_due = (invoice.total_incl_vat or D("0")) - (invoice.amount_paid or D("0"))
    if amount_d > balance_due:
        return None, "PAYMENT_EXCEEDS_BALANCE_DUE"

    if proof_file:
        from core.validators import validate_document_upload

        validate_document_upload(proof_file)

    # Idempotency: a bank reference uniquely identifies a real-world payment.
    # A double-submit with the same reference must not be counted twice.
    if reference:
        existing = Payment.objects.filter(invoice=invoice, reference=reference).first()
        if existing is not None:
            return existing, None

    try:
        # Savepoint so a unique-constraint hit (concurrent same-reference
        # insert that slipped past the check above) rolls back cleanly without
        # poisoning the outer transaction.
        with transaction.atomic():
            payment = Payment.objects.create(
                invoice=invoice,
                amount=amount_d,
                method=method,
                paid_at=paid_at,
                reference=reference,
                proof_file=proof_file,
                recorded_by=actor,
                # D2a: платёж — запись регистра, его печатный артефакт — квитанция.
                # Номер присваивается сразу (своя серия), PDF рендерится после коммита.
                receipt_number=_next_receipt_number(_invoice_seller_company(invoice)),
            )
    except IntegrityError:
        existing = Payment.objects.filter(invoice=invoice, reference=reference).first()
        if existing is not None:
            return existing, None
        raise

    invoice.amount_paid = (invoice.amount_paid or D("0")) + amount_d
    if invoice.amount_paid >= invoice.total_incl_vat:
        invoice.status = _istatus(InvoiceStatusCode.PAID)
    else:
        invoice.status = _istatus(InvoiceStatusCode.PARTIAL)
    invoice.save(update_fields=["amount_paid", "status", "updated_at"])

    marker = "[MANUAL_MODE] " if manual else ""
    ActivityLog.objects.create(
        action=f"{marker}Зафиксирован платёж",
        detail=f"Счёт {invoice.number}: получено {amount_d} (итого {invoice.amount_paid}/{invoice.total_incl_vat})",
        event_code="payment.recorded",
        # Decimals serialized as str (JSONField default encoder can't emit Decimal) — keeps the
        # exact value; the client formats currency by locale.
        event_params={
            "number": invoice.number,
            "amount": str(amount_d),
            "paid": str(invoice.amount_paid),
            "total": str(invoice.total_incl_vat),
            "manual": manual,
        },
        user=actor,
        level="SUCCESS",
        deal=invoice.deal,
        company_id=invoice.deal.company_id,
    )
    # Об оплате продавец не узнавал НИКАК — событие оседало только в журнале активности.
    # После коммита, чтобы уведомление не пережило откат транзакции.
    from .deal_emails import email_payment_received
    from .deal_notifications import notify_payment_recorded

    transaction.on_commit(lambda: notify_payment_recorded(payment))
    email_payment_received(payment)
    from ..tasks import render_document_pdf

    payment_id = payment.id
    transaction.on_commit(lambda: render_document_pdf.delay("receipt", payment_id))
    return payment, None


@transaction.atomic
def _act_wordings(seller_company) -> dict:
    """Снапшот формулировок акта на момент выпуска (E4)."""
    from accounts.models import CompanyDocumentProfile

    from ..document_wording import resolve_wording

    # Сырой ряд профиля (не брендовый резолвер _seller_document_profile — тот возвращает None
    # без legal_name/лого, а формулировки D1 живут в профиле независимо от брендинга).
    profile = CompanyDocumentProfile.objects.filter(company=seller_company).first() if seller_company else None
    return {"act_closing_text": resolve_wording(profile, "act_closing_text")}


# Нумератор держит блокировку счётчика ДО КОММИТА вызывающего (контракт
# `next_document_number`), поэтому выпуск акта обязан быть атомарным. Без декоратора продавец
# получал 500 на кнопку «Сформировать акт» — найдено проходом глазами 03-08.
@transaction.atomic
def generate_act(
    invoice_id: int,
    actor: Optional[CustomUser] = None,
) -> Tuple[Optional[object], Optional[str]]:
    from django.utils import timezone

    from accounts.services import is_seller

    from ..models import Act, Invoice

    # Issuing the act (acceptance certificate) is a seller-side action — own-company staff.
    if actor is not None and not (getattr(actor, "is_superuser", False) or is_seller(actor)):
        return None, "MEMBER_REQUIRED_FOR_ACTION"
    try:
        invoice = Invoice.objects.select_related("contract__quote", "deal", "status").get(pk=invoice_id)
    except Invoice.DoesNotExist:
        return None, "NOT_FOUND"
    if invoice.status_code not in {InvoiceStatusCode.PAID, InvoiceStatusCode.PARTIAL, InvoiceStatusCode.ISSUED}:
        return None, "ACT_INVALID_INVOICE_STATUS"

    # Закрывающий документ по счёту ОДИН. Защиты не было ни в модели, ни здесь: три нажатия
    # кнопки давали три акта с разными номерами на одну и ту же сумму (замер 24-08 — акты на
    # 336 при счёте на 112). Ни в одном эталоне второй закрывающий документ не рождается
    # кнопкой: в Odoo повторная валидация запрещена, исправление оформляется отдельной
    # сущностью (кредит-нота), в SAP — сторно. Такой сущности у нас нет, поэтому дубль
    # запрещён, а исправление идёт через аннулирование или повторный выпуск.
    live_act = Act.objects.filter(invoice=invoice).exclude(status__code=ActStatusCode.CANCELLED).order_by("-id").first()
    if live_act is not None:
        # Отклонённый акт возвращается в DRAFT, и интерфейс обещает заказчику «исполнитель
        # выставит акт заново». Выпускать ЗАНОВО надо тот же документ (Odoo подтверждает
        # черновик, а не плодит второй), поэтому здесь называем существующий, а не молчим.
        if live_act.status_code == ActStatusCode.DRAFT:
            return None, f"ACT_AWAITING_REISSUE:{live_act.id}"
        return None, f"ACT_ALREADY_EXISTS:{live_act.id}"

    # Seller company = the КП author's owning company → its prefix + per-company counter.
    from .document_blocks import frozen_body_for
    from .quotes import _quote_seller_company

    seller_company = _quote_seller_company(invoice.contract.quote) if invoice.contract_id else None
    act = Act.objects.create(
        deal=invoice.deal,
        contract=invoice.contract,
        invoice=invoice,
        number=_next_act_number(seller_company),
        status=_astatus(ActStatusCode.ISSUED),
        issued_at=timezone.localdate(),
        total_amount=invoice.total_incl_vat,
        # E3: акт рождается выпущенным — редакция шаблона замораживается сразу. Продавец
        # резолвится той же цепочкой, что при рендере (акт зеркалит счёт).
        frozen_template_body=frozen_body_for(seller_company or _invoice_seller_company(invoice), "ACT"),
        # E4: оговорка акта фиксируется при выпуске — правка профиля после не перепечатывает акт.
        wording_selections=_act_wordings(seller_company or _invoice_seller_company(invoice)),
        created_by=actor,
        # Титул исполнителя: выпуск — это первая из двух сторон акта (G2). Раньше подписант
        # не сохранялся вообще, и по документу нельзя было сказать, кто его выставил.
        issuer_signer=actor,
        issuer_signed_at=timezone.now(),
    )
    # Render off the request thread, after commit (F1.6 — avoids orphan PDFs on
    # rollback). The download endpoint renders lazily if a download races ahead.
    from ..tasks import render_document_pdf

    act_id = act.id
    transaction.on_commit(lambda: render_document_pdf.delay("act", act_id))
    # Покупателя о выставленном акте не извещал никто — он не мог узнать, что от него ждут
    # подпись, кроме как открыв реестр (который ему к тому же закрыт).
    from .deal_emails import email_act_awaiting_acceptance
    from .deal_notifications import notify_act_issued

    transaction.on_commit(lambda: notify_act_issued(act))
    email_act_awaiting_acceptance(act)
    return act, None


def _render_act_pdf(act) -> None:
    from io import BytesIO

    from django.core.files.base import ContentFile
    from django.template.loader import render_to_string
    from weasyprint import HTML

    # Real seller (via the act's contract → КП) so «От Поставщика» names the counterparty,
    # not a blank line. Shared branding bundle, same shape as every other document.
    from ..document_wording import document_wording_context
    from .documents import brand_context_for_pdf, document_brand_context, document_totals
    from .quotes import _quote_seller_company

    quote = act.contract.quote if (act.contract_id and act.contract.quote_id) else None
    supplier = _quote_seller_company(quote) if quote else None
    if supplier is None and act.invoice_id:
        # Акт по ручному счёту (волна K) не имеет договора → КП. Акт зеркалит счёт (D1),
        # поэтому и продавца берёт той же цепочкой fallback-ов — иначе «Поставщик» печатался
        # платформой, а «От Поставщика» пустой строкой.
        supplier = _invoice_seller_company(act.invoice)
    act_brand = document_brand_context(supplier)

    # D1: the act MIRRORS its invoice (audit: «акт зеркалит инвойс») — same net/VAT/gross figures,
    # same shared 3-line block. Falls back to the act's own gross total if it has no invoice.
    src_invoice = act.invoice
    ccy = src_invoice.currency.code if (src_invoice and src_invoice.currency_id) else "UZS"
    if src_invoice:
        totals = document_totals(
            ccy=ccy,
            subtotal=src_invoice.subtotal_excl_vat,
            vat_amount=src_invoice.vat_amount,
            total=src_invoice.total_incl_vat,
        )
    else:
        totals = document_totals(ccy=ccy, total=act.total_amount)

    # E1: если у компании (или у платформы) есть шаблон акта — печатаем по нему. Компания
    # правит ТЕКСТ своего документа, а структурные блоки вставляются плейсхолдерами и
    # собираются сервером. Шаблона нет → прежний путь из кода, документ не меняется.
    # E3: выпущенный акт печатает замороженную редакцию; блоки (штампы подписей) — живые.
    from .document_blocks import company_template_for, render_act_body

    frozen_body = act.frozen_template_body
    act_template = None if frozen_body else company_template_for(supplier, "ACT")
    if frozen_body or act_template is not None:
        html_string = render_to_string(
            "crm/act_pdf_templated.html",
            {
                "act": act,
                "invoice": act.invoice,
                "company": act.deal.company,
                "contact": act.deal.contact,
                "totals": totals,
                "body_html": render_act_body(
                    act,
                    act.invoice,
                    totals,
                    ccy,
                    act_template,
                    seller=act_brand.get("seller"),
                    seller_profile=act_brand.get("seller_profile"),
                    body_html=frozen_body or None,
                ),
                **brand_context_for_pdf(act_brand),
            },
        )
        buf = BytesIO()
        HTML(string=html_string).write_pdf(buf)
        act.pdf_file.save(f"Act_{act.number}.pdf", ContentFile(buf.getvalue()), save=True)
        return

    html_string = render_to_string(
        "crm/act_pdf.html",
        {
            "act": act,
            "invoice": act.invoice,
            "company": act.deal.company,
            "contact": act.deal.contact,
            "totals": totals,
            **brand_context_for_pdf(act_brand),
            # Оговорка о приёмке: компании либо платформенная (spec-documents-editable).
            **document_wording_context(act_brand.get("seller_profile")),
        },
    )
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    act.pdf_file.save(f"Act_{act.number}.pdf", ContentFile(buf.getvalue()), save=True)


@transaction.atomic
def act_viewer_side(actor, act) -> str:
    """Сторона зрителя по ЭТОМУ акту: «issuer» (выпустил), «acceptor» (принимает) или «».

    Акт двусторонний: выпускает исполнитель, принимает заказчик. Раньше сторона не
    различалась вовсе — кто первый нажал, тот и закрывал документ в одиночку.
    """
    from accounts.services import is_seller

    if actor is None or getattr(actor, "is_anonymous", False):
        return ""
    if is_seller(actor):
        return "issuer"
    # Заказчика-пользователя в ERP нет (FIX-13): приёмку акта вернёт портал (FIX-22), до тех пор
    # «acceptor» не выдаётся никому, и `sign_act` / `reject_act` изнутри ERP недостижимы.
    return ""


def _locked_act(act_id: int):
    """`of=("self",)` блокирует ТОЛЬКО строку акта. `Act.status` — nullable FK, поэтому
    `select_related("status")` даёт LEFT OUTER JOIN, а PostgreSQL запрещает `FOR UPDATE` по
    nullable-стороне внешнего соединения: без `of` запрос падал с NotSupportedError, то есть
    подписание акта отвечало 500.

    ⚠️ Любой вызывающий ОБЯЗАН быть `@transaction.atomic`: вне транзакции Django поднимает
    `TransactionManagementError`. Тесты этого не ловят — `pytest.mark.django_db` держит
    каждый тест в транзакции, поэтому дефект виден только в живом запросе (проход глазами
    03-08: приёмка акта отвечала 500). Инвариант закреплён `test_locked_paths_are_atomic.py`.
    """
    from ..models import Act

    return Act.objects.select_for_update(of=("self",)).select_related("status", "deal").get(pk=act_id)


@transaction.atomic
def sign_act(act_id: int, actor: CustomUser, signed_file=None) -> Tuple[Optional[object], Optional[str]]:
    """ЗАКАЗЧИК принимает выставленный акт → SIGNED (G2).

    Акт — двусторонний документ: в узбекской практике он «подтверждён двумя сторонами», в
    российском ЭДО состоит из двух титулов. Раньше здесь стояла ОДНА подпись без подписанта, и
    закрыть акт в одиночку могла любая сторона, включая выпустившую его.

    Подпись остаётся ручной ([MANUAL_MODE]): клик без E-IMZO не является юридически значимой
    подписью, поэтому фиксируем «согласовано в системе» с полным аудит-следом.
    """
    from django.utils import timezone

    act = _locked_act(act_id)
    if act.status_code != ActStatusCode.ISSUED:
        return None, "ACT_SIGN_NOT_ALLOWED"
    if act_viewer_side(actor, act) != "acceptor":
        # Выпустивший акт не может «принять» его сам — приёмка это подтверждение ВТОРОЙ стороны.
        return None, "ACT_ACCEPTOR_SIDE_REQUIRED"

    now = timezone.now()
    act.status = _astatus(ActStatusCode.SIGNED)
    act.signed_at = now
    act.acceptor_signer = actor
    act.acceptor_signed_at = now
    if signed_file is not None:
        act.signed_file = signed_file
    act.save(
        update_fields=[
            "status",
            "signed_at",
            "acceptor_signer",
            "acceptor_signed_at",
            "signed_file",
            "updated_at",
        ]
    )
    # [MANUAL_MODE]: a button-click / uploaded scan is NOT a qualified e-signature — tag it so
    # these records can be told apart from real E-IMZO signatures once that lands (tech debt,
    # see memory tech_debt_payment_esign). Mirrors the contract-sign logs in contracts.py.
    ActivityLog.objects.create(
        action="[MANUAL_MODE] Акт принят заказчиком",
        detail=f"Акт {act.number} по сделке #{act.deal_id}",
        event_code="act.signed",
        event_params={"number": act.number, "deal_id": act.deal_id, "manual": True},
        user=actor,
        level="SUCCESS",
        deal=act.deal,
        company_id=act.deal.company_id,
    )
    from .deal_notifications import notify_act_signed

    transaction.on_commit(lambda: notify_act_signed(act, actor))
    # Перерисовать PDF акта после приёмки: кэшированный файл создан при выпуске и не знает о
    # подписи заказчика (глазами 17-08 — скачанный «подписанный» акт с пустыми линиями).
    from ..tasks import render_document_pdf

    act_id = act.id
    transaction.on_commit(lambda: render_document_pdf.delay("act", act_id))
    return act, None


@transaction.atomic
def reject_act(act_id: int, actor: CustomUser, reason: str = "") -> Tuple[Optional[object], Optional[str]]:
    """ЗАКАЗЧИК отклоняет акт с указанием причины (G2).

    Второй шаг двустороннего цикла, которого не было вовсе: заказчик мог либо подписать, либо
    ничего — несогласие выразить было нечем, и документ повисал. Паттерн взят у ЭСФ, где
    покупатель «подтверждает или отклоняет», и у нашего же отклонения КП, где причина
    обязательна: без основания отказ бесполезен обеим сторонам.

    Акт возвращается в DRAFT — исполнитель правит и выпускает заново.
    """

    clean_reason = (reason or "").strip()
    if not clean_reason:
        return None, "REASON_REQUIRED"
    act = _locked_act(act_id)
    if act.status_code != ActStatusCode.ISSUED:
        return None, "ACT_SIGN_NOT_ALLOWED"
    if act_viewer_side(actor, act) != "acceptor":
        return None, "ACT_ACCEPTOR_SIDE_REQUIRED"

    act.status = _astatus(ActStatusCode.DRAFT)
    act.rejection_reason = clean_reason
    act.issuer_signed_at = None
    act.save(update_fields=["status", "rejection_reason", "issuer_signed_at", "updated_at"])
    ActivityLog.objects.create(
        action="Акт отклонён заказчиком",
        detail=f"Акт {act.number} по сделке #{act.deal_id}: {clean_reason}",
        event_code="act.rejected",
        event_params={"number": act.number, "deal_id": act.deal_id, "reason": clean_reason},
        user=actor,
        level="WARNING",
        deal=act.deal,
        company_id=act.deal.company_id,
    )
    from .deal_notifications import notify_act_rejected

    transaction.on_commit(lambda: notify_act_rejected(act, actor, clean_reason))
    return act, None


# ── Действия ВЫПУСТИВШЕЙ стороны по акту (A4 спеки карточки акта) ─────────────
#
# Двусторонний цикл (G2) дал заказчику два ответа — принять или вернуть с причиной, — но у
# исполнителя после выпуска не осталось ничего: акт висел, и сделать с ним было нечего.
# Эталоны закрывающих документов дают выпустившей стороне ровно два действия, и оба здесь.

#: Ручное напоминание — не чаще раза в сутки на документ. Ограничение взято у PandaDoc
#: (manual reminder «once every 24 hours»): без него кнопка превращается в инструмент спама,
#: а доставляемость считается по домену целиком — мусорные письма бьют по критичным.
ACT_REMINDER_COOLDOWN_HOURS = 24


@transaction.atomic
def reissue_act(act_id: int, actor: CustomUser) -> Tuple[Optional[object], Optional[str]]:
    """Исполнитель выпускает ЗАНОВО акт, который заказчик вернул с причиной.

    Отклонение возвращает акт в DRAFT, и диалог отказа прямо обещает заказчику: «исполнитель
    увидит причину и выставит акт заново». Пути для этого не существовало — у DRAFT-акта
    оставалась одна кнопка «Аннулировать», а «Сформировать акт» на счёте порождала ВТОРОЙ
    документ. Эталон — Odoo: исправленный черновик подтверждают, а не создают рядом второй.

    Редакция шаблона и формулировки замораживаются заново: это новая выдача документа, и
    печатать он должен то, что действует сейчас (E3/E4). Номер сохраняется — документ тот же.
    """
    from django.utils import timezone

    from .document_blocks import frozen_body_for

    act = _locked_act(act_id)
    if act.status_code != ActStatusCode.DRAFT:
        return None, "ACT_REISSUE_NOT_ALLOWED"
    # Выпустить акт заново может только сторона-исполнитель: заказчику, который вернул акт,
    # отвечаем «это не ваше действие».
    if act_viewer_side(actor, act) != "issuer":
        return None, "ACT_ISSUER_SIDE_REQUIRED"

    seller_company = _invoice_seller_company(act.invoice) if act.invoice_id else None
    act.status = _astatus(ActStatusCode.ISSUED)
    act.issued_at = timezone.localdate()
    act.issuer_signer = actor
    act.issuer_signed_at = timezone.now()
    # Причина прошлого отказа снимается с документа, но НЕ пропадает: она осталась в журнале
    # и в уведомлении — иначе на выпущенном заново акте висел бы чужой отказ.
    act.rejection_reason = ""
    act.frozen_template_body = frozen_body_for(seller_company, "ACT")
    act.wording_selections = _act_wordings(seller_company)
    act.save(
        update_fields=[
            "status",
            "issued_at",
            "issuer_signer",
            "issuer_signed_at",
            "rejection_reason",
            "frozen_template_body",
            "wording_selections",
            "updated_at",
        ]
    )
    ActivityLog.objects.create(
        action="Акт выпущен заново",
        detail=f"Акт {act.number} по сделке #{act.deal_id}",
        event_code="act.reissued",
        event_params={"number": act.number, "deal_id": act.deal_id},
        user=actor,
        level="INFO",
        deal=act.deal,
        company_id=act.deal.company_id,
    )

    from ..tasks import render_document_pdf
    from .deal_emails import email_act_awaiting_acceptance
    from .deal_notifications import notify_act_issued

    act_id_value = act.id
    transaction.on_commit(lambda: render_document_pdf.delay("act", act_id_value))
    transaction.on_commit(lambda: notify_act_issued(act))
    email_act_awaiting_acceptance(act)
    return act, None


@transaction.atomic
def remind_act_acceptance(act_id: int, actor: CustomUser) -> Tuple[Optional[object], Optional[str]]:
    """Исполнитель напоминает заказчику, что акт ждёт ответа.

    ВАЖНО: это ПОВТОР уже существующего письма «акт ждёт подтверждения», а не новый его вид —
    число писем на отрезке остаётся прежним (канон: их ровно четыре). Так же устроен «Resend»
    у DocuSign и manual reminder у PandaDoc: адресату уходит то же приглашение, а не другое
    сообщение.
    """
    from datetime import timedelta

    from django.utils import timezone

    act = _locked_act(act_id)
    if act.status_code != ActStatusCode.ISSUED:
        return None, "ACT_REMINDER_NOT_ALLOWED"
    if act_viewer_side(actor, act) != "issuer":
        return None, "ACT_ISSUER_SIDE_REQUIRED"
    if act.reminder_sent_at and timezone.now() - act.reminder_sent_at < timedelta(hours=ACT_REMINDER_COOLDOWN_HOURS):
        return None, "ACT_REMINDER_TOO_SOON"

    act.reminder_sent_at = timezone.now()
    act.save(update_fields=["reminder_sent_at", "updated_at"])
    ActivityLog.objects.create(
        action="Напоминание по акту",
        detail=f"Акт {act.number} по сделке #{act.deal_id}: заказчику отправлено напоминание",
        event_code="act.reminded",
        event_params={"number": act.number, "deal_id": act.deal_id},
        user=actor,
        level="INFO",
        deal=act.deal,
        company_id=act.deal.company_id,
    )
    from .deal_emails import email_act_awaiting_acceptance
    from .deal_notifications import notify_act_issued

    transaction.on_commit(lambda: notify_act_issued(act))
    email_act_awaiting_acceptance(act)
    return act, None


@transaction.atomic
def cancel_act(act_id: int, actor: CustomUser, reason: str = "") -> Tuple[Optional[object], Optional[str]]:
    """Исполнитель отзывает собственный акт с обязательной причиной.

    Эталон — void у DocuSign и cancel у Adobe Acrobat Sign: отозвать документ может ТОЛЬКО
    выпустившая сторона, причина уходит адресату вместе с уведомлением, а статус терминальный
    («unvoid» не существует ни там, ни там). Согласованный обеими сторонами акт не отзывается:
    это уже закрытый документ, и его судьба решается новым актом, а не правкой старого.
    """

    clean_reason = (reason or "").strip()
    if not clean_reason:
        return None, "REASON_REQUIRED"
    act = _locked_act(act_id)
    if act.status_code not in {ActStatusCode.DRAFT, ActStatusCode.ISSUED}:
        return None, "ACT_CANCEL_NOT_ALLOWED"
    if act_viewer_side(actor, act) != "issuer":
        return None, "ACT_ISSUER_SIDE_REQUIRED"

    act.status = _astatus(ActStatusCode.CANCELLED)
    act.cancellation_reason = clean_reason
    act.save(update_fields=["status", "cancellation_reason", "updated_at"])
    ActivityLog.objects.create(
        action="Акт аннулирован",
        detail=f"Акт {act.number} по сделке #{act.deal_id}: {clean_reason}",
        event_code="act.cancelled",
        event_params={"number": act.number, "deal_id": act.deal_id, "reason": clean_reason},
        user=actor,
        level="WARNING",
        deal=act.deal,
        company_id=act.deal.company_id,
    )
    from .deal_notifications import notify_act_cancelled

    transaction.on_commit(lambda: notify_act_cancelled(act, actor, clean_reason))
    return act, None


def _render_receipt_pdf(payment) -> None:
    """Квитанция об оплате (D2a, паттерн Odoo Payment Receipt): печатный артефакт платежа.

    Рендер по механике E1 — шаблон компании либо платформенный образец; структурные блоки
    собирает сервер. Номер квитанции присваивается при записи платежа (record_payment).
    """
    from io import BytesIO

    from django.core.files.base import ContentFile
    from django.template.loader import render_to_string
    from weasyprint import HTML

    from .document_blocks import company_template_for, render_receipt_body
    from .documents import brand_context_for_pdf, document_brand_context, document_totals

    invoice = payment.invoice
    supplier = _invoice_seller_company(invoice)
    brand = document_brand_context(supplier)
    ccy = invoice.currency.code if invoice.currency_id else "UZS"
    totals = document_totals(ccy=ccy, total=payment.amount)
    template = company_template_for(supplier, "RECEIPT")
    html_string = render_to_string(
        "crm/receipt_pdf_templated.html",
        {
            "payment": payment,
            "invoice": invoice,
            "company": invoice.deal.company,
            "contact": invoice.deal.contact,
            "body_html": render_receipt_body(
                payment,
                totals,
                ccy,
                template,
                seller=brand.get("seller"),
                seller_profile=brand.get("seller_profile"),
            ),
            **brand_context_for_pdf(brand),
        },
    )
    buf = BytesIO()
    HTML(string=html_string).write_pdf(buf)
    payment.pdf_file.save(f"Receipt_{payment.receipt_number}.pdf", ContentFile(buf.getvalue()), save=True)

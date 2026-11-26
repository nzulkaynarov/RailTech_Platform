"""Sample document for the settings screens: the REAL generator on a sample context (plan ДОК-14).

«Образец совпадает с документом, который получит клиент»: the sample of «Шаблоны» and «Реквизиты и бланк» is not a
second renderer. It builds in-memory stand-ins for the deal, the counterparty and the lines (nothing is saved, nothing
is sent) and passes them to the very functions that print working documents — `rt_documents.{quote,contract,invoice,
act}_pdf` for the four commercial kinds, `generated_pdf_bytes` for letters. The blank is the company's live one (or the
unsaved draft of the settings form), the body is the active template (or the unsaved text of the editor), the number is
the one the sequence would give next (`peek_document_number` — the counter is neither locked nor incremented) and the
language is the one a working document is printed in (`translation.override`).

The PDF is rendered off the request thread (B-094: the hard render timeout works in a worker's main thread): the view
queues `crm.render_document_sample`, the worker stores the result in the cache for a few minutes, the view reads it.
"""

from __future__ import annotations

import datetime
import logging
import uuid
from copy import copy
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Iterable

from django.core.cache import cache
from django.utils import timezone, translation

from core.currency import BASE_CURRENCY, line_amount

logger = logging.getLogger(__name__)

#: The kinds of the «Реквизиты и бланк» switch (КП, договор, счёт, акт, письмо) — storage codes of the numbering.
SAMPLE_KINDS = ("KP", "CT", "INV", "ACT", "DOC")

#: Template kind (editor of «Шаблоны») → the sample kind printed by its generator; any other kind prints as a letter.
TEMPLATE_KIND_SAMPLE = {"CONTRACT": "CT", "INVOICE": "INV", "ACT": "ACT"}

#: Languages a working document is printed in (platform locales).
SAMPLE_LANGUAGES = ("ru", "en", "uz")

#: How long a rendered sample waits for the screen to pick it up.
RESULT_TTL_SECONDS = 600

_VAT_RATE = Decimal("12")

# Draft values of the blank form that may be laid over the saved profile in memory (never saved; hex/choice values are
# neutralised by the render-time allowlists in `_brand_context_from_row`).
_TEXT_OVERRIDES = (
    "legal_name",
    "inn",
    "legal_address",
    "bank_details",
    "signatory_name",
    "signatory_position",
    "footer_text",
    "accent_color",
    "cover_letter_text",
)
_BOOL_OVERRIDES = (
    "use_company_defaults",
    "show_logo",
    "show_lead_time",
    "show_fx_note",
    "show_cover_letter",
    "show_bank_in_header",
)

_LETTER_BODY = (
    "<p>Настоящим гарантируем оплату по сделке в полном объёме в согласованные сроки.</p>"
    "<p>Сумма обязательств соответствует коммерческому предложению {kp} на сумму {total}.</p>"
)


@dataclass
class SampleResult:
    """The sample PDF and the placeholder codes of the template text the generator does not know."""

    pdf: bytes
    warnings: list[str] = field(default_factory=list)


class SampleError(Exception):
    """A request the sample cannot honour (unknown kind, oversize text); `code` is the API error code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# ── Sample context ────────────────────────────────────────────────────────────────────────────────────


def _buyer() -> SimpleNamespace:
    return SimpleNamespace(
        name="ООО «Образец-Клиент»",
        inn="300000000",
        legal_address="г. Ташкент, ул. Примерная, 1",
        contact_person="Директору Иванову К. К.",
        phone="",
        registration_number="",
        country=None,
    )


_LINES = (
    ("Подшипник буксовый ЦКБ тип 2726", "2726", "ГОСТ 24955-81", Decimal("10"), Decimal("1500000"), 21),
    ("Колодка тормозная композиционная", "", "", Decimal("40"), Decimal("85000"), None),
)


def _lines() -> list[SimpleNamespace]:
    """One set of lines for every kind: invoice/act rows (`description`, `unit_price_excl_vat`) and quote/contract rows
    (`imported_raw_name`, `final_price_excl_vat`) carry the same names and amounts."""
    rows = []
    for index, (name, mpn, gost, qty, price, lead) in enumerate(_LINES, start=1):
        total = line_amount(price, qty)
        rows.append(
            SimpleNamespace(
                line_no=index,
                description=name,
                imported_raw_name=name,
                mpn=mpn,
                gost_drawing=gost,
                lead_time_days=lead,
                product=None,
                product_id=None,
                source_quote_item=None,
                quantity=qty,
                unit="шт.",
                unit_price_excl_vat=price,
                final_price_excl_vat=price,
                line_total_excl_vat=total,
                line_total=total,
            )
        )
    return rows


class _Rows(list):
    """`invoice.items` of the act: the generator calls `.select_related(...)` on it."""

    def select_related(self, *_args):
        return self


def _quote_rows(rows: Iterable[SimpleNamespace]) -> list[dict[str, Any]]:
    """The client projection of the КП lines (dicts, as `client_projection_items` gives them)."""
    return [
        {
            "display_type": "ITEM",
            "line_no": row.line_no,
            "product": None,
            "imported_raw_name": row.imported_raw_name,
            "mpn": row.mpn,
            "gost_drawing": row.gost_drawing,
            "quantity": row.quantity,
            "unit": row.unit,
            "lead_time_days": row.lead_time_days,
            "final_price_excl_vat": row.final_price_excl_vat,
            "line_total": row.line_total,
        }
        for row in rows
    ]


def _totals(rows: list[SimpleNamespace]) -> dict:
    from .totals import document_totals

    subtotal = sum((row.line_total for row in rows), Decimal(0))
    vat = (subtotal * _VAT_RATE / Decimal(100)).quantize(Decimal("0.01"))
    return document_totals(
        ccy=BASE_CURRENCY,
        vat_rate=_VAT_RATE,
        subtotal=subtotal,
        vat_amount=vat,
        total=subtotal + vat,
        amount_paid=Decimal(0),
        balance_due=subtotal + vat,
    )


def _brand(company, overrides: dict | None) -> tuple[dict, Any]:
    """(blank of the company, the profile row it was built from): the saved blank, with the unsaved draft of the form
    laid over it in memory when there is one."""
    from accounts.models import CompanyDocumentProfile

    from .brand import _brand_context_from_row

    row = CompanyDocumentProfile.objects.filter(company=company).first()
    if overrides:
        if row is None:
            row = CompanyDocumentProfile(company=company)  # in memory only — never saved
        for name in _TEXT_OVERRIDES:
            if name in overrides:
                setattr(row, name, overrides[name] or "")
        for name in _BOOL_OVERRIDES:
            if name in overrides:
                value = overrides[name]
                if isinstance(value, str):
                    value = value.strip().lower() in {"1", "true", "yes", "on"}
                setattr(row, name, bool(value))
    # `_brand_context_from_row` rewrites the row with the company card (the card wins for the letterhead). The КП terms
    # of a working document read a fresh profile row (the profile wins there), so the sample hands them the row as it
    # was before the rewrite: same rule, same «Место отгрузки».
    untouched = copy(row) if row is not None else None
    return _brand_context_from_row(company, row), untouched


def template_body(company, kind_code: str, seed: str) -> str:
    """The body a working document of this kind is frozen from: the active template of the company, else the platform
    sample, else the seed of the generator."""
    from crm.services.document_blocks import company_template_for

    template = company_template_for(company, kind_code)
    return template.body_html if template is not None else seed


def template_warnings(company, user, body_html: str) -> list[str]:
    """Placeholder codes of the text that nothing resolves (the editor lists them); structural blocks of the kinds are
    assembled by the generator and are not warnings."""
    from crm.services.document_blocks import preview_block_stubs
    from crm.services.document_placeholders import render_template

    from ..generated_documents import demo_placeholder_context

    _html, _values, warnings = render_template(body_html, demo_placeholder_context(company, user))
    stubs = preview_block_stubs()
    return [code for code in warnings if code not in stubs]


def peek(company, code: str) -> str:
    from ..numbering import peek_document_number

    return peek_document_number(code, company=company)


def _sample_deal(buyer, now) -> SimpleNamespace:
    return SimpleNamespace(company=buyer, company_id=1, contact=None, number="", created_at=now)


def _contract(company, buyer, rows, totals, now, *, with_quote: bool = True) -> SimpleNamespace:
    deal = _sample_deal(buyer, now)
    quote = (
        SimpleNamespace(
            number=peek(company, "KP"),
            vat_rate=_VAT_RATE,
            effective_delivery_lead_time_days=21,
            delivery_basis=SimpleNamespace(code="DAP", name="Ташкент"),
        )
        if with_quote
        else None
    )
    return SimpleNamespace(
        number=peek(company, "CT"),
        created_at=now,
        valid_from=None,
        valid_until=None,
        notes="",
        total_amount=totals["total"],
        deal=deal,
        quote=quote,
        quote_id=1 if with_quote else None,
        template=None,
        wording_selections=None,
        verification_code="",
        signatory_name="",
        signatory_position="",
        signatory_basis_text="",
        signed_at=None,
        manager_signer_id=None,
        manager_signer=None,
        manager_signed_at=None,
        client_signer_id=None,
        client_signer=None,
        client_signed_at=None,
    )


# ── The real generators ───────────────────────────────────────────────────────────────────────────────


def _pdf_quote(company, brand, row, now) -> bytes:
    from ..documents import quote_document_extras, rt_documents

    buyer = _buyer()
    rows = _lines()
    totals = _totals(rows)
    quote = SimpleNamespace(
        number=peek(company, "KP"),
        version=1,
        deal_id=0,
        deal=_sample_deal(buyer, now),
        created_at=now,
        valid_until=(now + datetime.timedelta(days=30)).date(),
        quote_currency=SimpleNamespace(code=BASE_CURRENCY),
        vat_rate=_VAT_RATE,
        total_excl_vat=totals["subtotal"],
        vat_amount=totals["vat_amount"],
        total_incl_vat=totals["total"],
        effective_delivery_lead_time_days=21,
        delivery_basis=SimpleNamespace(code="DAP", name="Ташкент"),
        delivery_note="",
        payment_terms="100% предоплата",
        notes="",
        public_access_token=None,
        verification_code="",
        signatory_name="",
        signatory_position="",
        signatory_basis_text="",
        signed_at=None,
        prepared_by=SimpleNamespace(
            get_full_name=lambda: "Алексей Менеджеров", email="sales@company.uz", phone="+998 90 123-45-67"
        ),
    )
    extras = quote_document_extras(quote, company, profile_row=row)
    return rt_documents.quote_pdf(
        quote, items=_quote_rows(rows), optional_items=[], extras=extras, brand=brand, draft=False
    )


def _pdf_contract(company, brand, body_html, now, template=None) -> bytes:
    from core.seeds.documents import CONTRACT_BODY

    from ..documents import rt_documents

    rows = _lines()
    totals = _totals(rows)
    from .contract_frame import frame_of

    # Рамка (название, подписи сторон, «Основание») — у самого шаблона: не-поставка не показывает «КП №».
    contract = _contract(company, _buyer(), rows, totals, now, with_quote=frame_of(template).supply)
    body = body_html if body_html is not None else template_body(company, "CONTRACT", CONTRACT_BODY)
    return rt_documents.contract_pdf(contract, rows, totals, brand, draft=False, body_html=body, template=template)


def _pdf_invoice(company, brand, body_html, now) -> bytes:
    from core.seeds.documents import INVOICE_BODY

    from ..documents import rt_documents

    rows = _lines()
    totals = _totals(rows)
    contract = SimpleNamespace(number=peek(company, "CT"), created_at=now)
    invoice = SimpleNamespace(
        number=peek(company, "INV"),
        issued_at=now,
        created_at=now,
        due_date=(now + datetime.timedelta(days=10)).date(),
        contract_id=1,
        contract=contract,
        deal=_sample_deal(_buyer(), now),
        notes="",
        vat_amount=totals["vat_amount"],
        total_incl_vat=totals["total"],
    )
    body = body_html if body_html is not None else template_body(company, "INVOICE", INVOICE_BODY)
    return rt_documents.invoice_pdf(invoice, rows, totals, brand, draft=False, body_html=body)


def _pdf_act(company, brand, body_html, now) -> bytes:
    from core.seeds.documents import ACT_BODY

    from ..documents import rt_documents

    rows = _lines()
    totals = _totals(rows)
    contract = SimpleNamespace(number=peek(company, "CT"), created_at=now)
    invoice = SimpleNamespace(number=peek(company, "INV"), issued_at=now, items=_Rows(rows))
    act = SimpleNamespace(
        number=peek(company, "ACT"),
        issued_at=now,
        created_at=now,
        deal_id=0,
        deal=_sample_deal(_buyer(), now),
        contract_id=1,
        contract=contract,
        invoice=invoice,
        total_amount=totals["total"],
        wording_selections=None,
        verification_code="",
        signatory_name="",
        signatory_position="",
        signatory_basis_text="",
        issuer_signer_id=None,
        issuer_signer=None,
        issuer_signed_at=None,
        acceptor_signer_id=None,
        acceptor_signer=None,
        acceptor_signed_at=None,
    )
    body = body_html if body_html is not None else template_body(company, "ACT", ACT_BODY)
    return rt_documents.act_pdf(act, totals, brand, draft=False, body_html=body)


def _pdf_letter(company, user, brand, body_html, now) -> bytes:
    from crm.services.document_placeholders import render_template, sanitize_template_html

    from ..generated_documents import demo_placeholder_context, generated_pdf_bytes

    if body_html is None:
        rendered = _LETTER_BODY.format(kp=peek(company, "KP"), total="20 608 000 UZS")
    else:
        rendered, _values, _warnings = render_template(
            sanitize_template_html(body_html), demo_placeholder_context(company, user)
        )
    document = SimpleNamespace(
        title="Образец документа" if body_html is not None else "Гарантийное письмо",
        number=peek(company, "DOC"),
        created_at=now,
        rendered_html=rendered,
    )
    return generated_pdf_bytes(document, company, brand, is_draft=False)


def render_sample(
    company,
    user,
    *,
    kind: str,
    body_html: str | None = None,
    overrides: dict | None = None,
    language: str | None = None,
    template=None,
) -> SampleResult:
    """The PDF of a sample document of `kind` (see SAMPLE_KINDS). `body_html` — the unsaved text of the template editor;
    `overrides` — the unsaved draft of the blank form; `language` — the language the document is printed in."""
    from django.conf import settings

    if kind not in SAMPLE_KINDS:
        raise SampleError("INVALID_SAMPLE_KIND")
    language = language if language in SAMPLE_LANGUAGES else settings.LANGUAGE_CODE
    now = timezone.now()
    warnings: list[str] = []
    if body_html is not None:
        from crm.services.document_placeholders import sanitize_template_html
        from crm.services.generated_documents import MAX_TEMPLATE_BODY_CHARS

        if len(body_html) > MAX_TEMPLATE_BODY_CHARS:
            raise SampleError("TEMPLATE_BODY_TOO_LARGE")
        body_html = sanitize_template_html(body_html)
        warnings = template_warnings(company, user, body_html)
    with translation.override(language):
        brand, row = _brand(company, overrides)
        if kind == "KP":
            pdf = _pdf_quote(company, brand, row, now)
        elif kind == "CT":
            pdf = _pdf_contract(company, brand, body_html, now, template)
        elif kind == "INV":
            pdf = _pdf_invoice(company, brand, body_html, now)
        elif kind == "ACT":
            pdf = _pdf_act(company, brand, body_html, now)
        else:
            pdf = _pdf_letter(company, user, brand, body_html, now)
    return SampleResult(pdf=pdf, warnings=warnings)


# ── Queue: the view asks, the worker renders, the view reads ───────────────────────────────────────────


def _key(company_id: int, user_id: int, sample_id: str, part: str) -> str:
    return f"docsample:{company_id}:{user_id}:{sample_id}:{part}"


_DEFAULT_TEXT_CAP = 5000


def clean_draft(draft: Any) -> dict | None:
    """The unsaved blank of the form, reduced to what the blank has: known keys only, texts cut to the model's own
    limit — nothing else reaches the queue."""
    from accounts.models import CompanyDocumentProfile

    if not isinstance(draft, dict):
        return None
    cleaned: dict[str, Any] = {}
    for name in _TEXT_OVERRIDES:
        value = draft.get(name)
        if isinstance(value, str):
            limit = CompanyDocumentProfile._meta.get_field(name).max_length or _DEFAULT_TEXT_CAP
            cleaned[name] = value[:limit]
    for name in _BOOL_OVERRIDES:
        value = draft.get(name)
        if isinstance(value, bool):
            cleaned[name] = value
        elif isinstance(value, str):
            cleaned[name] = value[:8]
    return cleaned or None


def queue_sample(company, user, request: dict) -> str:
    """Put the sample in the render queue; returns its id. Nothing is rendered here."""
    from crm.tasks import render_document_sample

    kind = request.get("kind")
    if kind not in SAMPLE_KINDS:
        raise SampleError("INVALID_SAMPLE_KIND")
    from crm.services.generated_documents import MAX_TEMPLATE_BODY_CHARS

    body_html = request.get("body_html")
    if body_html is not None and len(body_html) > MAX_TEMPLATE_BODY_CHARS:
        raise SampleError("TEMPLATE_BODY_TOO_LARGE")
    request = {**request, "draft": clean_draft(request.get("draft"))}
    sample_id = uuid.uuid4().hex
    cache.set(_key(company.pk, user.pk, sample_id, "state"), {"status": "pending"}, RESULT_TTL_SECONDS)
    render_document_sample.delay(sample_id, company.pk, user.pk, request)
    return sample_id


def sample_state(company_id: int, user_id: int, sample_id: str) -> dict | None:
    """{"status": "pending" | "ready" | "failed", "warnings": [...], "failure_code": code} or None when unknown/expired."""
    return cache.get(_key(company_id, user_id, sample_id, "state"))


def sample_pdf(company_id: int, user_id: int, sample_id: str) -> bytes | None:
    return cache.get(_key(company_id, user_id, sample_id, "pdf"))


def run_sample(sample_id: str, company_id: int, user_id: int, request: dict) -> None:
    """The worker's side: render and store the PDF (or the error code) for the screen to read."""
    from documents.models import DocumentTemplate

    from accounts.models import Company, CustomUser

    company = Company.objects.get(pk=company_id)
    user = CustomUser.objects.get(pk=user_id)
    template_id = request.get("template_id")
    template = (
        DocumentTemplate.objects.filter(pk=template_id).filter(company_id=company_id).first()
        if isinstance(template_id, int)
        else None
    )
    try:
        result = render_sample(
            company,
            user,
            kind=request["kind"],
            body_html=request.get("body_html"),
            overrides=request.get("draft"),
            language=request.get("language"),
            template=template,
        )
    except SampleError as exc:
        cache.set(
            _key(company_id, user_id, sample_id, "state"),
            {"status": "failed", "failure_code": exc.code},
            RESULT_TTL_SECONDS,
        )
        return
    except Exception:  # noqa: BLE001 — fault barrier: the screen shows a code, the traceback goes to the log
        logger.exception("Sample document %s failed", request.get("kind"))
        cache.set(
            _key(company_id, user_id, sample_id, "state"),
            {"status": "failed", "failure_code": "SAMPLE_RENDER_FAILED"},
            RESULT_TTL_SECONDS,
        )
        return
    cache.set(_key(company_id, user_id, sample_id, "pdf"), result.pdf, RESULT_TTL_SECONDS)
    cache.set(
        _key(company_id, user_id, sample_id, "state"),
        {"status": "ready", "warnings": result.warnings},
        RESULT_TTL_SECONDS,
    )

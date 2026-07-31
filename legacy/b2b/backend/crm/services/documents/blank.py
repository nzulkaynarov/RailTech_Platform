"""КП «фирменный бланк» — сопроводительный текст, структурные условия, имя файла (spec-kp-blank).

ONE builder per block, shared by the real PDF render, its public HTML twin and the settings
preview — that is what keeps the three surfaces from drifting.
"""

import re

from .totals import document_totals


def _tidy_empty_substitutions(text: str) -> str:
    """Clean the punctuation residue an EMPTY token leaves behind.

    A flat substitution of «…за интерес, {{buyer}}.» with no buyer yields «…за интерес, .».
    Collapse the artifacts (empty brackets/quotes, space-before-punctuation, doubled
    punctuation, runs of spaces) so a missing counterparty never prints a dangling comma.
    Only runs when a token actually resolved to «» — normal seller text is left untouched.
    """
    text = re.sub(r"«\s*»|\(\s*\)|\"\s*\"", "", text)  # empty brackets/quotes
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)  # space before punctuation
    text = re.sub(r"([,;:])\s*([.,;:])", r"\2", text)  # doubled punctuation → keep the last
    text = re.sub(r"[ \t]{2,}", " ", text)  # collapse space runs
    text = re.sub(r"[ \t]+\n", "\n", text)  # trailing spaces per line
    return text.strip()


def substitute_tokens(text: str, **tokens) -> str:
    """Плоская подстановка `{{имя}}` → значение, с уборкой пунктуации после пустых токенов.

    Выделено из `resolve_cover_letter`, потому что тем же способом подставляются формулировки
    договора и акта (`crm.document_wording`): один механизм — одно место, где он может сломаться.
    Текст НЕ рендерится как Django-шаблон: подстановка строковая (нет SSTI), а вывод экранирует
    вызывающий шаблон через `|linebreaks` (нет XSS).
    """
    if not text:
        return ""
    values = {f"{{{{{name}}}}}": ("" if value is None else str(value)) for name, value in tokens.items()}
    had_empty = any(token in text and not value for token, value in values.items())
    for token, value in values.items():
        text = text.replace(token, value)
    return _tidy_empty_substitutions(text) if had_empty else text


def resolve_cover_letter(profile, *, buyer_name: str = "", deal_ref: str = "", seller_name: str = "") -> str:
    """Resolved cover-letter paragraph, or "" when disabled/empty.

    FLAT token substitution ({{buyer}}/{{deal}}/{{seller}}) — the stored text is NEVER rendered
    as a Django template (no SSTI). Values are inserted raw; the caller's template prints it via
    `|linebreaks`, which auto-escapes, so an injected value can't become markup (no XSS).

    `deal_ref` fills {{deal}} — the buyer's REQUEST reference. A заявка has no formal number
    (owner decision 27-07), so callers pass its date («на Ваш запрос от 24.07.2026»).
    """
    if not profile or not getattr(profile, "show_cover_letter", False):
        return ""
    text = (getattr(profile, "cover_letter_text", "") or "").strip()
    if not text:
        return ""
    return substitute_tokens(text, buyer=buyer_name or "", deal=deal_ref or "", seller=seller_name or "")


def build_quote_terms(
    *,
    shipment_place: str = "",
    lead_days=None,
    delivery_note: str = "",
    payment: str = "",
    incoterm: str = "",
    warranty_months=None,
    valid_until: str = "",
    other: str = "",
) -> list:
    """The structured «Условия поставки» rows (label:value) for the КП blank.

    Everything except «Прочие условия» is DYNAMIC — sourced from КП / seller data, not retyped.
    Empty values are skipped so a blank line never prints. ONE builder (Rule 8) shared by the
    real render and the settings preview, so the two can't drift.
    """
    rows = []

    def add(label, value):
        if value not in (None, "", 0):
            rows.append({"label": label, "value": value})

    add("Место отгрузки", shipment_place)
    if lead_days:
        srok = f"до {lead_days} дн."
        if delivery_note:
            srok = f"{srok} · {delivery_note}"
        add("Сроки поставки", srok)
    elif delivery_note:
        add("Сроки поставки", delivery_note)
    add("Условия оплаты", payment)
    add("Базис поставки", incoterm)
    if warranty_months:
        add("Гарантия", f"{warranty_months} мес.")
    add("Срок действия КП", valid_until)
    add("Прочие условия", other)
    return rows


def quote_pdf_filename(quote) -> str:
    """PDF filename derived from the КП's OWN number (the seller's numbering scheme) — the file a
    client saves must match the document it contains («КП-2026-00042_v2.pdf»), not an internal
    deal-id. Filesystem-unsafe characters collapse to «_» (cyrillic is kept — modern browsers,
    mail clients and Django's RFC-5987 Content-Disposition handle it). A draft with no number
    yet degrades to the legacy deal-scoped name so uniqueness never breaks."""
    number = (quote.number or "").strip()
    if not number:
        return f"KP_{quote.deal_id}_v{quote.version}.pdf"
    safe = re.sub(r"[^\w\-.]+", "_", number, flags=re.UNICODE).strip("_")
    return f"{safe}_v{quote.version}.pdf"


def quote_document_extras(quote, seller_company) -> dict:
    """The «фирменный бланк» extras shared by the КП PDF *and* its online twin (D1c): the resolved
    cover letter, the structured «Условия поставки», and the unified 3-line VAT totals. ONE builder
    so the PDF and the public page — the «оригинал» a client reaches by scanning the QR — can never
    diverge. Read-only (never creates a profile/settings row)."""
    from accounts.models import CompanyDocumentProfile, CompanySettings

    doc_profile = CompanyDocumentProfile.objects.filter(company=seller_company).first() if seller_company else None
    seller_settings = CompanySettings.objects.filter(company=seller_company).first() if seller_company else None
    buyer = quote.deal.company
    deal_created = getattr(quote.deal, "created_at", None)
    cover_text = resolve_cover_letter(
        doc_profile,
        buyer_name=getattr(buyer, "name", "") or "",
        deal_ref=deal_created.strftime("%d.%m.%Y") if deal_created else "",
        seller_name=getattr(seller_company, "name", "") or "",
    )
    incoterm = ""
    if quote.delivery_basis:
        incoterm = quote.delivery_basis.code
        if quote.delivery_basis.name:
            incoterm = f"{incoterm} ({quote.delivery_basis.name})"
    quote_terms = build_quote_terms(
        shipment_place=(
            getattr(doc_profile, "legal_address", "") or getattr(seller_company, "legal_address", "") or ""
        ),
        lead_days=quote.effective_delivery_lead_time_days,
        delivery_note=quote.delivery_note or "",
        payment=getattr(seller_settings, "default_payment_terms", "") or "",
        incoterm=incoterm,
        warranty_months=getattr(seller_settings, "default_warranty_months", None),
        valid_until=quote.valid_until.strftime("%d.%m.%Y") if quote.valid_until else "",
        other=quote.notes or "",
    )
    totals = document_totals(
        ccy=quote.quote_currency.code if quote.quote_currency else "UZS",
        vat_rate=quote.vat_rate,
        subtotal=quote.total_excl_vat,
        vat_amount=quote.vat_amount,
        total=quote.total_incl_vat,
    )
    return {"cover_text": cover_text, "quote_terms": quote_terms, "totals": totals}

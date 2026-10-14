"""The public no-login КП surface: its URL, its QR code, and its render context.

The page is the browser-facing twin of ``crm/templates/crm/quote_pdf.html``. It composes the
same shared builders the PDF does — that is what guarantees the two documents never diverge
and the confidentiality invariant (no landed_cost / margin / FX / goods-vs-charges) holds
identically on both surfaces.
"""

from typing import Optional

from .blank import quote_document_extras
from .brand import document_brand_context
from .projection import client_optional_items, client_projection_items


def public_quote_url(quote) -> Optional[str]:
    """Public no-login КП link built from the minted `public_access_token`, or None before send.
    ONE place owns the URL pattern (Rule 8) — shared by the send-email task and the PDF «Принять
    онлайн» CTA. Returns None when the token is unset (draft/preview → the CTA stays hidden)."""
    from django.conf import settings

    token = getattr(quote, "public_access_token", None)
    if not token:
        return None
    return f"{settings.FRONTEND_URL}/api/v1/public/quotes/{token}/"


def public_quote_qr(quote) -> Optional[str]:
    """SVG QR data-URI for the public «Принять онлайн» link (F-09), or None before send.

    Reuses public_quote_url so ONE place owns the URL pattern (Rule 8). SVG (not PNG) so the
    code stays crisp at any print size with no PIL rasterization, and it is embedded as a
    base64 `data:` URI because WeasyPrint fetches no network/CSP-blocked resources — it reads
    only inline/`data:` sources. Any failure degrades to None (the text-link CTA still renders),
    never a 500 in the off-thread PDF task.
    """
    url = public_quote_url(quote)
    if not url:
        return None
    try:
        import base64
        import io

        import qrcode
        import qrcode.image.svg as qrsvg

        image = qrcode.make(url, image_factory=qrsvg.SvgPathImage, box_size=11, border=2)
        buffer = io.BytesIO()
        image.save(buffer)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded}"
    except (ValueError, OSError, ImportError):
        return None


def public_quote_page_context(quote) -> dict:
    """Full render context for the public КП HTML page (Wave A) — the SAME client projection the
    PDF renders: `client_projection_items` / `client_optional_items` (charges distributed into
    per-line delivered prices, NO cost/margin/charges breakout) + the seller branding bundle.
    """
    from crm.services.quotes._shared import _quote_seller_company

    seller_company = _quote_seller_company(quote)
    projected_items = client_projection_items(quote)
    context = {
        "quote": quote,
        "items": projected_items,
        "optional_items": client_optional_items(quote),
        "company": quote.deal.company,
        # Offline client fallback for the «Покупатель» block (deal.company is NULL for a
        # seller-created deal with an offline contact).
        "contact": quote.deal.contact,
        # Mirror the PDF (#375): render the per-line «Срок» column only when at least one line
        # actually carries a lead time — otherwise it is a column of «—» duplicating the single
        # КП-level «Срок поставки» below.
        "has_line_lead_time": any(item.get("lead_time_days") for item in projected_items),
        "public_quote_url": public_quote_url(quote),
        # D1c: the online page is the PDF's twin — same cover letter, structured «Условия
        # поставки» and 3-line VAT totals (one shared builder), so the QR «оригинал» never
        # looks poorer than the attached PDF.
        **quote_document_extras(quote, seller_company),
        **document_brand_context(seller_company),
    }
    return context

"""Shared document-rendering helpers — the seller branding pipeline for every PDF.

Rule 8: logic lives here; the render functions are thin. The package is split by reason to
change, and this module is the stable import surface — callers keep importing from
`crm.services.documents` regardless of which submodule owns a helper:

  • `brand`       — the seller branding bundle + document theme (layout preset / font / accent)
  • `totals`      — the uniform «без НДС → НДС → Итого» bridge for all four document types
  • `projection`  — client-facing КП lines (charges spread in; the confidentiality boundary)
  • `blank`       — КП «фирменный бланк»: cover letter, structured terms, PDF filename
  • `public_page` — the public no-login КП: URL, QR, render context
  • `draft`       — «ПРОЕКТ» до выпуска: единое поле контекста шаблона и имя кэшированного PDF (SIGN-1)
  • `preview`     — «образец» documents for the Document-Layout settings preview
"""

from .blank import build_quote_terms, quote_document_extras, quote_pdf_filename, resolve_cover_letter
from .brand import accent_contrast, brand_context_for_pdf, document_brand_context, seller_logo_url
from .draft import (
    act_is_draft,
    contract_is_draft,
    draft_context,
    generated_is_draft,
    invoice_is_draft,
    pdf_is_stale,
    quote_is_draft,
    remember_pdf_state,
)
from .preview import PREVIEW_DOC_TYPES, render_document_profile_preview_html
from .projection import client_optional_items, client_projection_items
from .public_page import public_quote_page_context, public_quote_qr, public_quote_url
from .totals import document_totals

__all__ = [
    "PREVIEW_DOC_TYPES",
    "accent_contrast",
    "act_is_draft",
    "brand_context_for_pdf",
    "build_quote_terms",
    "client_optional_items",
    "client_projection_items",
    "contract_is_draft",
    "document_brand_context",
    "document_totals",
    "draft_context",
    "remember_pdf_state",
    "generated_is_draft",
    "invoice_is_draft",
    "pdf_is_stale",
    "public_quote_page_context",
    "public_quote_qr",
    "public_quote_url",
    "quote_is_draft",
    "quote_document_extras",
    "quote_pdf_filename",
    "render_document_profile_preview_html",
    "resolve_cover_letter",
    "seller_logo_url",
]

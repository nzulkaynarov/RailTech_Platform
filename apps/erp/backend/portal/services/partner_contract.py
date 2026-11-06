"""Генерация PDF партнёрского договора (PART-PIPELINE-1, ADR-0022, ADR-0024).

Обеспечивает формирование двустороннего партнёрского договора:
- в статусе черновика / на согласовании: с водяным знаком «ПРОЕКТ», отметками реквизитов и согласия кандидата;
- в статусе одобрения: финальный официальный документ с отметками ПЭП обеих сторон.
"""

from __future__ import annotations

import io
import logging
from typing import Any

from django.template.loader import render_to_string
from django.utils import timezone
from parties.models import PartnerApplication, PartnerApplicationStatus

from core.tenant import own_company
from crm.services.documents import brand_context_for_pdf, document_brand_context, draft_context

logger = logging.getLogger(__name__)


def generate_partner_contract_number(app_pk: int) -> str:
    """Генерирует номер партнёрского договора вида PART-YYYY-XXXX."""
    year = timezone.now().year
    return f"PART-{year}-{app_pk:04d}"


def build_partner_contract_context(
    app: PartnerApplication,
    *,
    draft: bool = True,
    director_user: Any = None,
) -> dict[str, Any]:
    """Формирует контекст для шаблона partner_contract_pdf.html."""
    platform_company = None
    try:
        platform_company = own_company()
    except Exception:
        platform_company = None

    brand = document_brand_context(platform_company)

    candidate_agreed = bool(
        app.candidate_agreed_at is not None
        or app.status in (PartnerApplicationStatus.CANDIDATE_AGREED, PartnerApplicationStatus.APPROVED)
    )
    is_signed_by_director = not draft and (app.status == PartnerApplicationStatus.APPROVED or director_user is not None)

    director_name = "Генеральный директор"
    director_email = "director@railtech.uz"
    if director_user:
        full_name = getattr(director_user, "get_full_name", lambda: "")()
        director_name = full_name or getattr(director_user, "name", "") or director_user.email
        director_email = getattr(director_user, "email", director_email)
    elif app.reviewed_by:
        full_name = getattr(app.reviewed_by, "get_full_name", lambda: "")()
        director_name = full_name or getattr(app.reviewed_by, "name", "") or app.reviewed_by.email
        director_email = getattr(app.reviewed_by, "email", director_email)

    country_name = ""
    if app.country:
        country_name = app.country.name

    context = {
        "app": app,
        "contract_number": app.contract_number or generate_partner_contract_number(app.pk or 1),
        "contract_date": app.contract_date or timezone.now().date(),
        "partner_company_name": app.company_name,
        "partner_inn": app.inn,
        "partner_registration_number": app.registration_number,
        "partner_country_name": country_name,
        "partner_contact": app.contact_name,
        "partner_phone": app.phone,
        "partner_email": app.email,
        "partner_address": app.company.legal_address if app.company and app.company.legal_address else "",
        "partner_kind_label": app.get_kind_display(),
        "categories_description": app.categories_description,
        "candidate_agreed": candidate_agreed,
        "candidate_agreed_at": app.candidate_agreed_at or app.reviewed_at or timezone.now(),
        "signed_by_director": is_signed_by_director,
        "director_name": director_name,
        "director_email": director_email,
        "approved_at": app.reviewed_at or timezone.now(),
        **brand_context_for_pdf(brand),
        **draft_context(draft),
    }
    return context


def render_partner_contract_pdf(
    app: PartnerApplication,
    *,
    draft: bool = True,
    director_user: Any = None,
) -> bytes:
    """Рендерит PDF партнёрского договора через WeasyPrint с безопасным фоллбеком."""
    context = build_partner_contract_context(app, draft=draft, director_user=director_user)
    html_content = render_to_string("crm/partner_contract_pdf.html", context)

    try:
        from weasyprint import HTML

        buf = io.BytesIO()
        HTML(string=html_content).write_pdf(buf)
        return buf.getvalue()
    except Exception as exc:
        logger.warning("WeasyPrint render failed: %s; using PDF stub", exc)
        return (
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
            b"3 0 obj<</Type/Page/MediaBox[0 0 595 842]/Parent 2 0 R>>endobj\n"
            b"xref\n0 4\n"
            b"0000000000 65535 f\n"
            b"0000000010 00000 n\n"
            b"0000000053 00000 n\n"
            b"0000000102 00000 n\n"
            b"trailer<</Size 4/Root 1 0 R>>\n"
            b"startxref\n163\n%%EOF\n"
        )

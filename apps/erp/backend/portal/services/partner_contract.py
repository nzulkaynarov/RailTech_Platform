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
from parties.models import PartnerApplication

from core.tenant import own_company
from crm.services.documents import brand_context_for_pdf, document_brand_context, draft_context

logger = logging.getLogger(__name__)

#: Право подписывать договоры от своей компании: без него сотрудник на договоре подписантом не печатается (FX-1).
SIGN_PERMISSION = "contract.sign"


class PartnerContractRenderError(Exception):
    """PDF договора не собрался: заглушка договором не считается и не сохраняется (FX-1)."""


def _may_sign(user: Any) -> bool:
    from accounts.services.permissions import member_has_permission
    from core.tenant import own_company_id

    return member_has_permission(user, own_company_id(), SIGN_PERMISSION)


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

    # Согласие печатается только по факту согласования: одобрение в обход согласия его не означает (FX-1).
    candidate_agreed = app.candidate_agreed_at is not None

    # Подпись от нашей стороны — только у того, кому положено подписывать; иначе строка «Подпись / дата» (FX-1).
    signer = director_user or app.reviewed_by
    is_signed_by_director = not draft and signer is not None and _may_sign(signer)
    director_name = ""
    director_email = ""
    if is_signed_by_director:
        full_name = getattr(signer, "get_full_name", lambda: "")()
        director_name = full_name or getattr(signer, "name", "") or signer.email
        director_email = getattr(signer, "email", "")

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
        "candidate_agreed_at": app.candidate_agreed_at,
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
    """Рендерит PDF партнёрского договора через WeasyPrint; сбой — `PartnerContractRenderError`, заглушки нет (FX-1)."""
    context = build_partner_contract_context(app, draft=draft, director_user=director_user)
    html_content = render_to_string("crm/partner_contract_pdf.html", context)

    try:
        from weasyprint import HTML

        buf = io.BytesIO()
        HTML(string=html_content).write_pdf(buf)
    except Exception as exc:
        logger.exception("Partner contract render failed for application %s", app.pk)
        raise PartnerContractRenderError(str(exc)) from exc
    return buf.getvalue()

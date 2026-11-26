"""Партнёрский договор из утверждённого шаблона библиотеки (ПД-1, владелец 2026-11-25; ДОК-10).

Встроенного образца договора больше нет: договор кандидата — это либо утверждённый шаблон вида «партнёр»
(`documents.DocumentTemplate`, `counterparty_kind = partner`, утверждает держатель права `contract.approve_template`),
отрисованный данными заявки на языке договора, либо файл, который загрузил сотрудник. Шаблона и файла нет — отправлять
нечего, сотруднику это названо словами (`PartnerContractNotPrepared`).

Правила — настройки компании (`CompanySettings.contract_*`), не код: шаблон по умолчанию (`default_partner_contract_template`),
допустимость отступлений (`contract_deviations_allowed`).
"""

from __future__ import annotations

import io
import logging
from typing import Any

from django.template.defaultfilters import linebreaks
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import escape
from django.utils.safestring import mark_safe
from documents.models.documents import CounterpartyKind, DocumentTemplate
from parties.models import PartnerApplication

from core.tenant import own_company
from crm.services.documents import brand_context_for_pdf, document_brand_context, draft_context

logger = logging.getLogger(__name__)

LANGUAGES = ("ru", "en", "uz")


class PartnerContractRenderError(Exception):
    """PDF договора не собрался: заглушка договором не считается и не сохраняется (FX-1)."""


class PartnerContractUnfilled(Exception):
    """В тексте шаблона остались места без значения: договор с «{{…}}» кандидату не уходит."""

    def __init__(self, codes: list[str]):
        super().__init__(", ".join(codes))
        self.codes = codes


def generate_partner_contract_number(app_pk: int) -> str:
    """Номер партнёрского договора `<метка>-YYYY-XXXX`: метка — вид PART схемы нумерации (по умолчанию PA)."""
    from crm.services.numbering import OWN_FORMAT_WIDTH, own_format_number, type_label

    return own_format_number(type_label("PART"), timezone.now().year, app_pk, OWN_FORMAT_WIDTH["PART"])


# ── Библиотека шаблонов ────────────────────────────────────────────────────────────────────────────────────────────


def offered_partner_templates() -> list[DocumentTemplate]:
    """Утверждённые действующие шаблоны вида «партнёр» своей компании: то, из чего сотрудник готовит договор."""
    from crm.services.contract_templates import offered_templates

    company = _own_company_or_none()
    if company is None:
        return []
    return sorted(offered_templates(company, CounterpartyKind.PARTNER), key=lambda t: (t.name, -t.edition))


def default_partner_template_id() -> int | None:
    from crm.services.contract_templates import contract_rules

    company = _own_company_or_none()
    return contract_rules(company)["default_partner"] if company is not None else None


def template_languages(template: DocumentTemplate) -> list[str]:
    """На каких языках у шаблона есть свой текст; русский есть всегда."""
    languages = ["ru"]
    if (template.body_html_en or "").strip():
        languages.append("en")
    if (template.body_html_uz or "").strip():
        languages.append("uz")
    return languages


def deviations_allowed() -> bool:
    from crm.services.contract_templates import contract_rules

    company = _own_company_or_none()
    return contract_rules(company)["deviations_allowed"] if company is not None else True


def _own_company_or_none():
    try:
        return own_company()
    except Exception:
        return None


# ── Отрисовка ──────────────────────────────────────────────────────────────────────────────────────────────────────

_WORDS = {
    "ru": {
        "title": "Договор",
        "number": "Договор № {number}",
        "from": "от {date}",
        "parties": "Реквизиты и подписи Сторон",
        "ours": "Компания",
        "theirs": "Партнёр",
        "inn": "ИНН",
        "reg": "Рег. номер",
        "country": "Страна",
        "contact": "Контакт",
        "sign": "Подпись / дата",
        "notes": "Дополнительные условия",
    },
    "en": {
        "title": "Agreement",
        "number": "Agreement No. {number}",
        "from": "dated {date}",
        "parties": "Details and signatures of the Parties",
        "ours": "Company",
        "theirs": "Partner",
        "inn": "Tax ID",
        "reg": "Registration No.",
        "country": "Country",
        "contact": "Contact",
        "sign": "Signature / date",
        "notes": "Additional terms",
    },
    "uz": {
        "title": "Şartnoma",
        "number": "Şartnoma № {number}",
        "from": "{date} sanasida",
        "parties": "Tomonlarning rekvizitlari va imzolari",
        "ours": "Kompaniya",
        "theirs": "Hamkor",
        "inn": "STIR",
        "reg": "Röyxatdan ötiş raqami",
        "country": "Davlat",
        "contact": "Aloqa",
        "sign": "Imzo / sana",
        "notes": "Qöşimça şartlar",
    },
}


def _body_for(template: DocumentTemplate, language: str) -> str:
    """Текст шаблона на языке договора; нет своего текста — русский (язык выбирает сотрудник, список — `template_languages`)."""
    body = {"en": template.body_html_en, "uz": template.body_html_uz}.get(language) or ""
    return body if body.strip() else template.body_html


def _party(title: str, name: str, lines: list[str]) -> str:
    rows = "".join(f"<p>{escape(line)}</p>" for line in lines if line)
    return f"<td><p><strong>{escape(title)}</strong></p><p><strong>{escape(name)}</strong></p>{rows}</td>"


def _requisites_block(app: PartnerApplication, brand: dict, words: dict) -> str:
    profile, seller = brand.get("seller_profile"), brand.get("seller")
    our_name = (getattr(profile, "legal_name", "") or getattr(seller, "name", "") or "").strip()
    our_inn = getattr(profile, "inn", "") or getattr(seller, "inn", "") or ""
    our_address = getattr(profile, "legal_address", "") or getattr(seller, "legal_address", "") or ""
    their_id = (
        f"{words['inn']}: {app.inn}"
        if app.inn
        else (f"{words['reg']}: {app.registration_number}" if app.registration_number else "")
    )
    country = f"{words['country']}: {app.country.name}" if app.country else ""
    address = app.company.legal_address if app.company_id and app.company.legal_address else ""
    ours = _party(words["ours"], our_name, [f"{words['inn']}: {our_inn}" if our_inn else "", our_address])
    theirs = _party(
        words["theirs"],
        app.company_name,
        [their_id, country, address, f"{words['contact']}: {app.contact_name}, {app.email}"],
    )
    sign = escape(words["sign"])
    signs = (
        f'<td style="padding-top:28pt">________________<br><small>{sign}</small></td>'
        f'<td style="padding-top:28pt">________________<br><small>{sign}</small></td>'
    )
    return (
        f"<h2>{escape(words['parties'])}</h2>"
        f'<table style="width:100%"><tr>{ours}{theirs}</tr><tr>{signs}</tr></table>'
    )


def render_partner_contract_body(
    app: PartnerApplication,
    template: DocumentTemplate,
    language: str,
    brand: dict,
    *,
    number: str,
    date,
    notes: str = "",
) -> str:
    """Тело шаблона с подставленными данными заявки. Незнакомые и пустые места — `PartnerContractUnfilled`."""
    from crm.services.document_blocks import _wording_html, format_document_date, render_document_body
    from crm.services.document_placeholders import extract_placeholders

    words = _WORDS[language]
    profile = brand.get("seller_profile")
    company = _own_company_or_none()
    empty = mark_safe("")
    blocks = {
        # Блоки, связанные со сделкой, у партнёрского договора пусты: товара и суммы в нём нет.
        "doc.spec_table": empty,
        "doc.totals": empty,
        # Одобренное отступление входит в текст договора (ДОК-10): как «Дополнительные условия» у клиентов
        "doc.notes": mark_safe(f"<h2>{escape(words['notes'])}</h2>{linebreaks(escape(notes))}") if notes else empty,
        "doc.extra_terms_article": empty,
        "doc.contract_acceptance": _wording_html(profile, "contract_acceptance_text"),
        "doc.contract_liability": _wording_html(profile, "contract_liability_text"),
        "doc.requisites_and_signatures": mark_safe(_requisites_block(app, brand, words)),
    }
    formatted_date = format_document_date(date)
    scalars = {
        "doc.number": number,
        "doc.date": formatted_date,
        "doc.total": "",
        "doc.currency": "",
        "doc.vat_rate": "",
        "doc.delivery_terms": "",
        "doc.valid_from": "",
        "doc.valid_until": "",
        "contract.number": number,
        "counterparty.name": app.company_name,
        "counterparty.inn": app.inn or app.registration_number,
        "company.name": getattr(company, "name", "") or "",
        "company.inn": getattr(company, "inn", "") or "",
        "company.address": getattr(company, "legal_address", "") or "",
        "today": formatted_date,
        "user.full_name": "",
        "user.email": "",
    }
    source = _body_for(template, language)
    # Незнакомые места проверяются по ТЕКСТУ ШАБЛОНА до подстановки: значения кандидата (в том числе с «{{…}}») места не создают
    known = set(blocks) | set(scalars)
    unknown = [code for code in extract_placeholders(source) if code not in known]
    if unknown:
        raise PartnerContractUnfilled(unknown)
    # Значения скаляров экранируются при подстановке, блоки собраны здесь из экранированных частей
    body = render_document_body(source, blocks=blocks, scalars=scalars)
    return body


def render_partner_contract_pdf(
    app: PartnerApplication, template: DocumentTemplate, language: str, *, number: str, date, notes: str = ""
) -> bytes:
    """PDF договора по утверждённому шаблону; сбой — `PartnerContractRenderError`, заглушки нет (FX-1)."""
    if language not in LANGUAGES:
        language = "ru"
    brand = document_brand_context(_own_company_or_none())
    body = render_partner_contract_body(app, template, language, brand, number=number, date=date, notes=notes)
    words = _WORDS[language]
    context: dict[str, Any] = {
        "body_html": body,
        "doc_title": (template.name or "").strip() or words["title"],
        "doc_number_line": words["number"].format(number=number),
        "doc_date_line": words["from"].format(date=date.strftime("%d.%m.%Y")),
        "html_lang": language,
        **brand_context_for_pdf(brand),
        **draft_context(False),
    }
    html_content = render_to_string("crm/partner_contract_templated.html", context)
    try:
        from weasyprint import HTML

        buf = io.BytesIO()
        HTML(string=html_content).write_pdf(buf)
    except Exception as exc:
        logger.exception("Partner contract render failed for application %s", app.pk)
        raise PartnerContractRenderError(str(exc)) from exc
    return buf.getvalue()

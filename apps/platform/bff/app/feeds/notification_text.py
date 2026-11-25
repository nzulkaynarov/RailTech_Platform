"""Заголовки уведомлений ERP на языке сотрудника (колокольчик Платформы).

ERP хранит `event_code` и `event_params` и пишет русский `title` — запасной вариант. Здесь — каталог
заголовков для событий, которые сотрудник решает или читает чаще всего (согласование КП, визы,
решение директора, смена реквизитов, карточки партнёра, договор). Русский — собственный `title` ERP:
он точнее шаблона. Нет события в каталоге или нет нужного параметра — остаётся `title` ERP.
Узбекский — только новая латиница (Ö Ğ Ş Ç, ʼ).
"""

import re
from typing import Any

_PLACEHOLDER = re.compile(r"\{(\w+)\}")

CATALOG: dict[str, dict[str, str]] = {
    "quote.approval_your_turn": {
        "en": "Quote approval needed",
        "uz": "Tijorat taklifini kelişiş kerak",
    },
    "quote.approval_returned": {
        "en": "Quote returned for rework",
        "uz": "Tijorat taklifi qayta işlaşga qaytarildi",
    },
    "quote.director_approved": {
        "en": "Quote approved",
        "uz": "Tijorat taklifi maʼqullandi",
    },
    "quote.director_rejected": {
        "en": "Quote rejected",
        "uz": "Tijorat taklifi rad etildi",
    },
    "quote.visas_complete": {
        "en": "Approvals collected",
        "uz": "Vizalar yiğildi",
    },
    "quote.visas_complete_informed": {
        "en": "Quote — for information",
        "uz": "Tijorat taklifi — maʼlumot uçun",
    },
    "portal.bank_change_requested": {
        "en": "Bank details change request: {company}",
        "uz": "Bank rekvizitlarini özgartiriş sörovi: {company}",
    },
    "contract.deviation_requested": {
        "en": "Contract template deviation request",
        "uz": "Şartnoma şablonidan çetga çiqiş sörovi",
    },
    "partner.crm_conflict": {
        "en": "Partner “{company}”: the CRM client already belongs to another company",
        "uz": "Hamkor «{company}»: CRMdagi mijoz boşqa kompaniyaga biriktirilgan",
    },
    "partner.crm_unverified": {
        "en": "Partner “{company}”: client handover from CRM is held until checked",
        "uz": "Hamkor «{company}»: CRMdan mijozni topşiriş tekşiruvgaça töxtatilgan",
    },
    "contract.email_failed": {
        "en": "Email with contract {number} was not delivered",
        "uz": "{number} şartnomasi bilan xat yetkazilmadi",
    },
    "invoice.email_failed": {
        "en": "Email with invoice {number} was not delivered",
        "uz": "{number} hisobi bilan xat yetkazilmadi",
    },
    "act.email_failed": {
        "en": "Email with act {number} was not delivered",
        "uz": "{number} dalolatnomasi bilan xat yetkazilmadi",
    },
    "invitation.email_failed": {
        "en": "Cabinet invitation was not delivered: {number}",
        "uz": "Kabinetga taklif yetkazilmadi: {number}",
    },
    "supplier_order.email_failed": {
        "en": "Email with order {number} was not delivered",
        "uz": "{number} buyurtmasi bilan xat yetkazilmadi",
    },
    "contract.signed_client": {
        "ru": "Клиент согласовал договор {number}",
        "en": "The client agreed to contract {number}",
        "uz": "Mijoz {number} şartnomasini kelişdi",
    },
}


def localized_title(event_code: str, params: Any, language: str) -> str | None:
    """Заголовок на `language` или `None` — тогда берётся `title` ERP (русский)."""
    template = CATALOG.get(event_code, {}).get(language)
    if template is None:
        return None
    values = params if isinstance(params, dict) else {}
    names = _PLACEHOLDER.findall(template)
    if any(not isinstance(values.get(n), str | int) or values.get(n) == "" for n in names):
        return None
    return template.format(**{n: values[n] for n in names})

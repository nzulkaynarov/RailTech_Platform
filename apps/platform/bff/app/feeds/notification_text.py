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
        "uz": "Tijorat taklifini kelishish kerak",
    },
    "quote.approval_returned": {
        "en": "Quote returned for rework",
        "uz": "Tijorat taklifi qayta ishlashga qaytarildi",
    },
    "quote.director_approved": {
        "en": "Quote approved by the director",
        "uz": "Tijorat taklifi direktor tomonidan maʼqullandi",
    },
    "quote.director_rejected": {
        "en": "Quote rejected by the director",
        "uz": "Tijorat taklifi direktor tomonidan rad etildi",
    },
    "quote.visas_complete": {
        "en": "Approvals collected",
        "uz": "Vizalar yiğildi",
    },
    "quote.visas_complete_informed": {
        "en": "Quote — for information",
        "uz": "Tijorat taklifi — maʼlumot uchun",
    },
    "portal.bank_change_requested": {
        "en": "Bank details change request: {company}",
        "uz": "Bank rekvizitlarini özgartirish sörovi: {company}",
    },
    "contract.deviation_requested": {
        "en": "Contract template deviation request",
        "uz": "Shartnoma shablonidan chetga chiqish sörovi",
    },
    "partner.crm_conflict": {
        "en": "Partner “{company}”: the CRM client already belongs to another company",
        "uz": "Hamkor «{company}»: CRMdagi mijoz boshqa kompaniyaga biriktirilgan",
    },
    "partner.crm_unverified": {
        "en": "Partner “{company}”: client handover from CRM is held until checked",
        "uz": "Hamkor «{company}»: CRMdan mijozni topshirish tekshiruvgacha toxtatilgan",
    },
    "contract.signed_client": {
        "ru": "Клиент согласовал договор {number}",
        "en": "The client agreed to contract {number}",
        "uz": "Mijoz {number} shartnomasini kelishdi",
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

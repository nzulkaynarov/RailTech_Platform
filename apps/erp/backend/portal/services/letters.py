"""Письма компании в кабинете — проекция из событий EDS (ЛИД-8, ADR-0026).

* `uz.railtech.eds.letter.registered.v2` → входящее компании (`in`): квитанция о регистрации ВХ;
* `uz.railtech.eds.document.registered.v2` с блоком `document.letter` → наше исходящее (`out`); если это ответ на
  входящее той же компании — входящее становится «Отвечено».

Чьё письмо — только по явной связи (ADR-0026 п. 2): сделка ERP → её компания; без сделки — точное совпадение ИНН
отправителя (`in`) или получателя (`out`) с ИНН компании ERP. Совпадения нет — письмо в кабинет не попадает (запись в
журнал, не ошибка: повтор события ничего бы не изменил). Повтор события — та же строка (ключ — id в EDS).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

from django.db import transaction
from parties.models import Company
from portal.models import LetterDirection, LetterState, PortalLetter
from sales.models import Deal

logger = logging.getLogger(__name__)


@dataclass
class Outcome:
    applied: bool
    reason: str = ""


def _when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _owner(deal_id: Optional[int], inn: Optional[str]) -> tuple[Optional[Company], Optional[Deal]]:
    """Компания письма: по сделке, иначе по точному ИНН; по названию — никогда."""
    deal = Deal.objects.select_related("company").filter(pk=deal_id).first() if deal_id else None
    if deal is not None and deal.company_id:
        return deal.company, deal
    if inn:
        return Company.objects.filter(inn=inn).first(), deal
    return None, deal


@transaction.atomic
def apply_letter_registered(data: dict[str, Any]) -> Outcome:
    """Входящее письмо компании зарегистрировано в EDS — квитанция в кабинете компании-отправителя."""
    letter = data.get("letter") or {}
    links = data.get("links") or {}
    sender = letter.get("sender") or {}
    company, deal = _owner(links.get("erp_deal_id") or links.get("erp_request_id"), sender.get("inn"))
    if company is None:
        logger.info(
            "eds.letter.registered %s: компания не найдена по сделке и ИНН — не в кабинет", letter.get("number")
        )
        return Outcome(False, "no_company")
    registered_at = _when(letter["registered_at"])
    _, created = PortalLetter.objects.update_or_create(
        eds_id=letter["eds_letter_id"],
        defaults={
            "company": company,
            "deal": deal,
            "direction": LetterDirection.IN,
            "number": letter["number"],
            "subject": letter["subject"],
            "date": date.fromisoformat(letter["received_at"]),
            "registered_at": registered_at,
        },
        create_defaults={
            "company": company,
            "deal": deal,
            "direction": LetterDirection.IN,
            "state": LetterState.REGISTERED,
            "number": letter["number"],
            "subject": letter["subject"],
            "date": date.fromisoformat(letter["received_at"]),
            "registered_at": registered_at,
        },
    )
    return Outcome(True, "created" if created else "updated")


@transaction.atomic
def apply_document_registered(data: dict[str, Any]) -> Outcome:
    """Исходящее письмо отправлено (ИСХ) — в кабинет компании-получателя; ответ закрывает входящее «Отвечено»."""
    document = data.get("document") or {}
    block = document.get("letter")
    if document.get("kind") != "letter_out" or block is None:
        return Outcome(False, "not_letter_out")
    recipient = block.get("recipient") or {}
    company, deal = _owner(document.get("erp_deal_id"), recipient.get("inn"))
    if company is None:
        logger.info(
            "eds.document.registered %s: компания не найдена по сделке и ИНН — не в кабинет", document.get("number")
        )
        return Outcome(False, "no_company")
    registered_at = _when(document["registered_at"])
    reply_to = block.get("in_reply_to") or {}
    values = {
        "company": company,
        "deal": deal,
        "direction": LetterDirection.OUT,
        "state": LetterState.SENT,
        "number": document["number"],
        "subject": document["subject"],
        "date": registered_at.date(),
        "registered_at": registered_at,
        "reply_number": reply_to.get("number") or "",
        "in_reply_to_eds_id": reply_to.get("eds_letter_id"),
    }
    _, created = PortalLetter.objects.update_or_create(eds_id=document["eds_document_id"], defaults=values)
    if reply_to.get("eds_letter_id"):
        # Ответ закрывает входящее только той же компании: чужое письмо по совпадению id не трогаем.
        PortalLetter.objects.filter(
            eds_id=reply_to["eds_letter_id"], company=company, direction=LetterDirection.IN
        ).update(state=LetterState.ANSWERED, reply_number=document["number"])
    return Outcome(True, "created" if created else "updated")

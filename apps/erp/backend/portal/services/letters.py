"""Письма компании в кабинете — проекция из событий EDS (ЛИД-8, ADR-0026).

* `uz.railtech.eds.letter.registered.v2` → входящее компании (`in`): квитанция о регистрации ВХ;
* `uz.railtech.eds.document.registered.v2` с блоком `document.letter` → наше исходящее (`out`); если это ответ на
  входящее той же компании — входящее становится «Отвечено».

Чьё письмо — только по явной связи (ADR-0026 п. 2): сделка ERP → её компания; у входящего — компания ERP, которую
указал регистратор EDS (`links.erp_company_id`, аудит сущностей С-7); иначе — точное совпадение ИНН отправителя (`in`)
или получателя (`out`) с ИНН компании ERP. Совпадения нет — письмо в кабинет не попадает (запись в
журнал, не ошибка: повтор события ничего бы не изменил). Повтор события — та же строка (ключ — id в EDS).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Optional

import httpx
from django.conf import settings
from django.db import transaction
from django.db.models import Q, QuerySet
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


def _owner(
    deal_id: Optional[int], inn: Optional[str], company_id: Optional[int] = None
) -> tuple[Optional[Company], Optional[Deal]]:
    """Компания письма: по сделке, иначе по связи с компанией ERP, иначе по точному ИНН; по названию — никогда."""
    deal = Deal.objects.select_related("company").filter(pk=deal_id).first() if deal_id else None
    if deal is not None and deal.company_id:
        return deal.company, deal
    linked = Company.objects.filter(pk=company_id).first() if company_id else None
    if linked is not None:
        return linked, deal
    if inn:
        return Company.objects.filter(inn=inn).first(), deal
    return None, deal


@transaction.atomic
def apply_letter_registered(data: dict[str, Any]) -> Outcome:
    """Входящее письмо компании зарегистрировано в EDS — квитанция в кабинете компании-отправителя."""
    letter = data.get("letter") or {}
    links = data.get("links") or {}
    sender = letter.get("sender") or {}
    company, deal = _owner(
        links.get("erp_deal_id") or links.get("erp_request_id"), sender.get("inn"), links.get("erp_company_id")
    )
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


# ── Чтение для кабинета (портал, модуль `letters`) ─────────────────────────────────────────────────────────────────

#: Сколько ждём PDF у EDS: письмо — несколько страниц, EDS во внутренней сети.
EDS_TIMEOUT_SECONDS = 15


class LetterFileUnavailable(Exception):
    """EDS не отдал файл (нет токена, сеть, 5xx): кабинет получает 503 и повторяет позже."""


def company_letters(
    company: Company,
    *,
    direction: Optional[str] = None,
    deal_id: Optional[int] = None,
    q: str = "",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
) -> QuerySet[PortalLetter]:
    """Письма компании сессии, новые сверху; фильтры — по контракту `GET /letters`."""
    letters = PortalLetter.objects.filter(company=company).select_related("deal")
    if direction:
        letters = letters.filter(direction=direction)
    if deal_id is not None:
        letters = letters.filter(deal_id=deal_id)
    if q:
        letters = letters.filter(Q(number__icontains=q) | Q(subject__icontains=q))
    if date_from:
        letters = letters.filter(date__gte=date_from)
    if date_to:
        letters = letters.filter(date__lte=date_to)
    return letters


def find_company_letter(company: Company, pk: int) -> Optional[PortalLetter]:
    """Письмо только своей компании: чужое — как несуществующее (404 без утечки)."""
    return PortalLetter.objects.filter(company=company, pk=pk).select_related("deal").first()


def letter_pdf(letter: PortalLetter) -> Optional[bytes]:
    """PDF нашего исходящего у EDS по сервисному токену (ADR-0026 п. 4). `None` — у EDS такого файла нет (404)."""
    token = settings.SERVICE_TOKEN_ERP_TO_EDS
    if not token:
        raise LetterFileUnavailable("SERVICE_TOKEN_ERP_TO_EDS is not set")
    url = f"{settings.EDS_INTERNAL_URL}/api/v1/service/letters/{letter.eds_id}/pdf"
    try:
        response = httpx.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=EDS_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        raise LetterFileUnavailable(str(exc)) from exc
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        logger.warning("eds letter pdf %s: HTTP %s", letter.eds_id, response.status_code)
        raise LetterFileUnavailable(f"HTTP {response.status_code}")
    return response.content

"""Передача клиента и заявки из CRM в ERP (CONTRACTS §2, M3-ERP-01; FIX-31, I-4, I-5, I-20).

Идемпотентно по `crm_client_id`:

- Повторный вызов (с любым `Idempotency-Key`) — 200 с теми же `erp_company_id`, `erp_request_id`; второй сделки,
  второго приглашения и вторых событий нет.
- Первый вызов — 201: компания ищется по `crm_client_id`, затем по ИНН. ИНН компании, уже связанной с другим
  `crm_client_id`, — `INN_CONFLICT` (409), ничего не создаётся и не переписывается. Компания без связи с CRM
  (заведена сотрудником) находится по ИНН и связывается, а не дублируется.
- Сопоставление `CrmClientMapping` создаётся ДО сделки и приглашения: события `request.created` и `invite.sent`
  строятся по нему и без него молча отбрасываются (`webhooks.build_event_envelope`).
- Заявка начинается со стадии FSM `DRAFT` (`stages.initial_fsm_stage`); `request.created` уходит с `source=crm` — его
  источник ставит `Deal.request_origin`, который читает `integration.signals`.
- Согласие (`consent.given_at`, `consent.version`) сохраняется на компании как пришло.
- В `invite.sent_via` — только то, что реально ушло (`invite_contact_to_portal`): письмо; Telegram принадлежит CRM, ERP в
  него не пишет.

Параллельные вызовы одного клиента (двойной клик, повтор по таймауту) и двух клиентов с одним ИНН сериализует
транзакционная рекомендательная блокировка PostgreSQL: сначала по `crm_client_id`, затем по ИНН. Уникальные
индексы (`CrmClientMapping.crm_client_id`, `Company.inn`) остаются последним рубежом.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.db import IntegrityError, connection, transaction
from django.utils.dateparse import parse_datetime
from parties.models import Company, CompanyType, Contact
from portal.models import PortalRequestLine
from portal.services.invitation import invite_contact_to_portal

from crm.models import Deal

from ..exceptions import IntegrationConflict
from ..models import CrmClientMapping, CrmContactMapping
from . import stages
from .webhooks import build_actor

logger = logging.getLogger(__name__)

INN_CONFLICT = "INN_CONFLICT"
_LOCK_NAMESPACE = "integration.handoff"


def _advisory_lock(kind: str, value: Any) -> None:
    """Блокировка до конца транзакции: вторая передача того же клиента (или ИНН) ждёт первую и видит её результат."""
    digest = hashlib.sha256(f"{_LOCK_NAMESPACE}:{kind}:{value}".encode()).digest()
    key = int.from_bytes(digest[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [key])


def _normalized_inn(company_data: Dict[str, Any]) -> Optional[str]:
    return (company_data.get("inn") or "").strip() or None


def _cabinet_url() -> str:
    return getattr(settings, "CABINET_URL", "http://cabinet.localhost")


def _repeat_response(mapping: CrmClientMapping) -> Dict[str, Any]:
    """Ответ на повторную передачу: те же id; в `sent_via` — то, что реально было отправлено контакту раньше."""
    company = mapping.company
    deal = company.deals.order_by("created_at", "id").first()
    primary = company.contacts.filter(is_primary=True).first() or company.contacts.first()
    invited = bool(primary and primary.invited_at)
    return {
        "erp_company_id": company.id,
        "erp_request_id": deal.id if deal else None,
        "invite": {"sent_via": ["email"] if invited else [], "cabinet_url": _cabinet_url()},
    }


def _consent(company: Company, consent: Dict[str, Any]) -> None:
    """Согласие кладётся на компанию как пришло; уже сохранённое не перезаписывается (повтор его не меняет)."""
    if company.consent_given_at is not None:
        return
    given_at = consent["given_at"]
    if isinstance(given_at, str):
        given_at = parse_datetime(given_at)
    company.consent_given_at = given_at
    company.consent_version = str(consent["version"]).strip()
    company.save(update_fields=["consent_given_at", "consent_version"])


def _get_or_create_company(data: Dict[str, Any], crm_client_id: int) -> Company:
    """Компания по ИНН либо новая. ИНН чужого клиента CRM — 409 `INN_CONFLICT` до любых записей."""
    c_data = data["company"]
    inn = _normalized_inn(c_data)
    if inn:
        _advisory_lock("inn", inn)
        existing = Company.objects.filter(inn=inn).first()
        if existing is not None:
            mapping = CrmClientMapping.objects.filter(company=existing).first()
            if mapping is not None and mapping.crm_client_id != crm_client_id:
                logger.warning(
                    "Handoff of CRM client #%s: INN is bound to CRM client #%s", crm_client_id, mapping.crm_client_id
                )
                raise IntegrationConflict(INN_CONFLICT)
            return existing

    language = c_data.get("language") or "ru"
    company = Company.objects.create(
        name=c_data["name"].strip(),
        inn=inn,
        stated_inn=inn or "",
        language=language,
        is_registered=True,
    )
    client_type = CompanyType.objects.filter(code="CLIENT").first()
    if client_type:
        company.types.add(client_type)
    return company


def _create_contacts(company: Company, data: Dict[str, Any]) -> Tuple[List[Contact], Optional[Contact]]:
    """Контакты с сопоставлениями; контакт компании с тем же e-mail не задваивается, а получает сопоставление."""
    language = data["company"].get("language") or "ru"
    contacts: List[Contact] = []
    primary: Optional[Contact] = None
    for item in data["contacts"]:
        email = (item.get("email") or "").strip().lower()
        is_primary = item.get("is_primary", False)
        contact = Contact.objects.filter(company=company, email__iexact=email).first() if email else None
        if contact is None:
            telegram_user_id = item.get("telegram_user_id")
            if telegram_user_id and Contact.objects.filter(telegram_user_id=telegram_user_id).exists():
                # Один Telegram-аккаунт — один контакт (уникальный индекс): чужую привязку не перехватываем и не падаем.
                logger.warning(
                    "Handoff: telegram_user_id of CRM contact #%s is bound to another contact", item["crm_contact_id"]
                )
                telegram_user_id = None
            contact = Contact.objects.create(
                company=company,
                name=item["name"].strip(),
                phone=(item.get("phone") or "").strip(),
                email=email,
                telegram_user_id=telegram_user_id,
                language=item.get("language") or language,
                is_primary=is_primary,
                preferred_channel=item.get("preferred_channel", "both"),
                can_act=True,
            )
        CrmContactMapping.objects.get_or_create(crm_contact_id=item["crm_contact_id"], defaults={"contact": contact})
        contacts.append(contact)
        if is_primary or primary is None:
            primary = contact
    return contacts, primary


def _create_request(company: Company, contact: Optional[Contact], data: Dict[str, Any], crm_client_id: int) -> Deal:
    """Заявка из передачи: стадия FSM `DRAFT`, `request.created(source=crm)` рождает сигнал по `request_origin`."""
    summary = data["need"]["summary"]
    deal = Deal(
        company=company,
        contact=contact,
        stage=stages.initial_fsm_stage(),
        title=f"Заявка: {company.name}",
        notes=summary,
    )
    deal.request_origin = {  # читает integration.signals: единственный request.created для этой сделки
        "source": "crm",
        "summary": summary,
        "actor": build_actor(actor_type="staff", name=(data.get("owner") or {}).get("name")),
        "crm_client_id": crm_client_id,
    }
    deal.save()
    for idx, item_text in enumerate(data["need"].get("product_interest") or []):
        PortalRequestLine.objects.create(deal=deal, text=str(item_text).strip(), sort_order=idx + 1)
    return deal


def _invite(contact: Optional[Contact], channels: List[str]) -> List[str]:
    """Приглашение в Cabinet; возвращает каналы, по которым оно РЕАЛЬНО ушло (сбой доставки передачу не роняет)."""
    if contact is None:
        return []
    effective = "both" if len(channels) > 1 else (channels[0] if channels else "email")
    result, error = invite_contact_to_portal(contact=contact, channel=effective, language=contact.language)
    if error:
        logger.info("Handoff invite for contact #%s was not sent: %s", contact.id, error)
        return []
    return [result["channel"]]


def process_client_handoff(data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Обработка handoff клиента из CRM в ERP. Возвращает (response_data, created)."""
    crm_client_id = data["crm_client_id"]
    try:
        with transaction.atomic():
            return _handoff(data, crm_client_id)
    except IntegrityError:
        # Последний рубеж гонки, которую не поймала блокировка: победитель уже зафиксирован — отвечаем по нему.
        mapping = CrmClientMapping.objects.filter(crm_client_id=crm_client_id).select_related("company").first()
        if mapping is None:
            raise
        return _repeat_response(mapping), False


def _handoff(data: Dict[str, Any], crm_client_id: int) -> Tuple[Dict[str, Any], bool]:
    _advisory_lock("client", crm_client_id)

    mapping = CrmClientMapping.objects.filter(crm_client_id=crm_client_id).select_related("company").first()
    if mapping is not None:
        return _repeat_response(mapping), False

    company = _get_or_create_company(data, crm_client_id)
    # Сопоставление — ДО сделки и приглашения: события строятся по нему.
    CrmClientMapping.objects.create(crm_client_id=crm_client_id, company=company)
    _consent(company, data["consent"])

    _contacts, primary = _create_contacts(company, data)

    deal = _create_request(company, primary, data, crm_client_id) if data.get("create_request") else None
    sent_via = _invite(primary, list(data.get("invite", {}).get("channels") or ["email"]))

    return {
        "erp_company_id": company.id,
        "erp_request_id": deal.pk if deal else None,
        "invite": {"sent_via": sent_via, "cabinet_url": _cabinet_url()},
    }, True

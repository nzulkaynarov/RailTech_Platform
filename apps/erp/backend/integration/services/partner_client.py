"""Партнёр становится клиентом CRM (PART-CRM, решение владельца 2026-11-04: «партнёр = клиент + «Мои товары»»).

CRM — источник правды по клиентам и контактам, поэтому ERP клиента не заводит, а просит CRM событием шины:

1. **Запрос.** Сотрудник приглашает партнёра в кабинет (`portal/desk/service.py`, `invite`): если компания не сопоставлена
   клиенту CRM (`CrmClientMapping`), в той же транзакции в outbox уходит `partner.client_requested` — реквизиты компании и
   контакты с e-mail (`request_client_in_crm`). Повторное приглашение, пока сопоставления нет, публикует его снова; CRM
   дедуплицирует по `erp_company_id` и id события. Откат приглашения (письмо не ушло) откатывает и событие.
2. **Ответ.** CRM находит клиента (по `erp_company_id`, ИНН, паре «страна + рег. номер») или создаёт и отвечает
   `crm.partner.client_resolved` (`apply_client_resolved`):
   `linked` — ставится `CrmClientMapping`, компании добавляется тип `CLIENT` (кабинет даёт ей клиентские модули поверх
   партнёрских — роли складываются, `portal/services/access.py`), контакты сопоставляются с контактами CRM, и заявки партнёра,
   созданные до сопоставления, публикуются (`DeferredRequestEvent`);
   `conflict` — найденный клиент уже сопоставлен другой компании ERP: ничего не переписывается, состояние запоминается
   (`PartnerCrmLink`), ответственному за партнёра уходит уведомление.
3. **Дальше** заявки партнёра идут обычным `request.created`, а название и ИНН компании обновляют штатные `crm.client.updated`.

Что видит сотрудник в блоке «Доступ в кабинет» — `crm_client_state`: `linked` / `requested` / `conflict` / `none`.
Ответ идемпотентен по `erp_company_id`: повтор не задваивает сопоставления, события и записи журнала.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone
from parties.models import Company, CompanyRelationship, CompanyType, Contact, RelationshipRole, active_contact_q
from rt_bus import Event

from crm.models import ActivityLog

from ..bus import get_bus
from ..models import CrmClientMapping, CrmContactMapping, DeferredRequestEvent, PartnerCrmLink, PartnerCrmStatus
from . import events
from .event_builders import _crm_user_id, build_actor, event_type_name
from .handoff import _advisory_lock

logger = logging.getLogger(__name__)

LINKED = "linked"
REQUESTED = "requested"
CONFLICT = "conflict"
NONE = "none"

APPLIED = "applied"
SKIPPED_UNKNOWN_COMPANY = "skipped_unknown_company"
SKIPPED_OTHER_CLIENT = "skipped_other_client"

#: `maxItems` контактов в событии (контракт).
MAX_CONTACTS = 50

_LOCK_KIND = "partner_client"


@dataclass(frozen=True)
class Outcome:
    status: str
    detail: str = ""

    @property
    def applied(self) -> bool:
        return self.status == APPLIED


def _text(value: Optional[str], limit: int) -> Optional[str]:
    clean = (value or "").strip()
    return clean[:limit] if clean else None


def _country_code(company: Company) -> Optional[str]:
    country = company.country
    code = (getattr(country, "alpha2", "") or getattr(country, "code", "") or "").strip().upper() if country else ""
    return code if len(code) == 2 and code.isalpha() else None


def _language(value: Optional[str], default: str = "ru") -> str:
    return value if value in ("ru", "uz", "en") else default


def _contacts(company: Company) -> List[Dict[str, Any]]:
    """Активные контакты компании с годным e-mail: по нему CRM ищет совпадение; без адреса контакт CRM не опознать."""
    rows: List[Dict[str, Any]] = []
    for contact in Contact.objects.filter(active_contact_q(), company=company).order_by("-is_primary", "name", "id"):
        email = (contact.email or "").strip().lower()
        if not email or len(email) > 255:
            continue
        try:
            validate_email(email)
        except ValidationError:
            continue
        rows.append(
            {
                "erp_contact_id": contact.pk,
                "full_name": (contact.name or email).strip()[:255],
                "email": email,
                "phone": _text(contact.phone, 50),
                "language": _language(contact.language, _language(company.language)),
            }
        )
    return rows[:MAX_CONTACTS]


def build_request_data(company: Company, user: Any = None) -> Optional[Dict[str, Any]]:
    """`data` события `partner.client_requested`; `None` — слать нечего (у компании нет контактов с e-mail)."""
    contacts = _contacts(company)
    if not contacts:
        return None
    data: Dict[str, Any] = {
        "erp_company_id": company.pk,
        "company": {
            "name": company.name.strip()[:255],
            "inn": _text(company.inn, 32),
            "registration_number": _text(company.registration_number, 64),
            "country": _country_code(company),
            "address": _text(company.legal_address, 1000),
            "website": _text(company.website, 255),
            "language": _language(company.language),
        },
        "contacts": contacts,
        "actor": build_actor(user=user, actor_type="staff" if user is not None else "system"),
    }
    crm_user_id = _crm_user_id(user)
    if crm_user_id:
        data["invited_by_crm_user_id"] = int(crm_user_id)
    return data


def request_client_in_crm(company: Company, user: Any = None) -> Optional[Event]:
    """Попросить CRM завести (или найти) клиента для компании партнёра. Вызывать внутри `transaction.atomic()` приглашения.

    `None` — просить не нужно: компания уже сопоставлена клиенту CRM, либо у неё нет контакта с e-mail. Ошибка публикации
    (`data` не по схеме) идёт наружу и откатывает приглашение.
    """
    if CrmClientMapping.objects.filter(company=company).exists():
        return None
    data = build_request_data(company, user)
    if data is None:
        return None
    PartnerCrmLink.objects.update_or_create(
        company=company,
        defaults={"status": PartnerCrmStatus.REQUESTED, "requested_at": timezone.now(), "resolved_at": None},
    )
    return get_bus().publish(event_type_name("partner.client_requested"), data, subject=f"company/{company.pk}")


# ── Ответ CRM ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def _log(company: Company, code: str, action: str, detail: str, level: str = "INFO", **params: Any) -> None:
    ActivityLog.objects.create(
        action=action,
        detail=detail,
        event_code=code,
        event_params={"company_id": company.pk, **params},
        level=level,
        entity_type="company",
        entity_id=company.pk,
        company_id=company.pk,
    )


def _notify_conflict(company: Company, crm_client_id: int, other_company_id: Optional[int]) -> None:
    """Ответственному за партнёра (иначе администраторам): клиент CRM уже сопоставлен другой компанией ERP."""
    from notifications.services import notify_platform_admins, notify_user

    relationship = (
        CompanyRelationship.objects.filter(company=company, role=RelationshipRole.PARTNER)
        .select_related("responsible")
        .first()
    )
    title = f"Партнёр «{company.name}»: клиент в CRM уже занят другой компанией"
    other = f" (компания ERP #{other_company_id})" if other_company_id else ""
    message = (
        f"CRM нашла клиента #{crm_client_id} с теми же реквизитами, но он уже сопоставлен другой компании{other}. "
        "Ничего не изменено, заявки партнёра остаются в ERP. Откройте клиента в CRM и объедините карточки, затем "
        "пригласите партнёра ещё раз."
    )
    params = {"company": company.name, "crm_client_id": crm_client_id}
    code = "partner.crm_conflict"
    if relationship is not None and relationship.responsible_id:
        notify_user(
            user=relationship.responsible,
            title=title,
            message=message,
            type_code="WARNING",
            event_code=code,
            event_params=params,
        )
    else:
        notify_platform_admins(title=title, message=message, type_code="WARNING", event_code=code, event_params=params)


def _map_contacts(company: Company, items: List[Mapping[str, Any]]) -> int:
    """Сопоставить контакты запроса контактам CRM. Уже сопоставленный контакт и занятый номер CRM пропускаются."""
    mapped = 0
    for item in items:
        contact = Contact.objects.filter(pk=int(item["erp_contact_id"]), company=company).first()
        if contact is None:
            continue
        crm_contact_id = int(item["crm_contact_id"])
        if CrmContactMapping.objects.filter(contact=contact).exists():
            continue
        if CrmContactMapping.objects.filter(crm_contact_id=crm_contact_id).exists():
            logger.warning("partner client: CRM contact #%s is already mapped, skipped", crm_contact_id)
            continue
        CrmContactMapping.objects.create(crm_contact_id=crm_contact_id, contact=contact)
        mapped += 1
    return mapped


def release_deferred_requests(company: Company, crm_client_id: int) -> int:
    """Опубликовать `request.created` заявок партнёра, созданных до сопоставления. Идемпотентно: опубликованная помечена."""
    released = 0
    pending = (
        DeferredRequestEvent.objects.select_for_update()
        .select_related("deal")
        .filter(deal__company=company, published_at__isnull=True)
        .order_by("id")
    )
    for row in pending:
        deal = row.deal
        summary = getattr(getattr(deal, "portal_summary", None), "text", None) or deal.title
        events.publish_request_created(
            deal, source="cabinet", erp_request_id=deal.pk, summary=summary, crm_client_id=crm_client_id
        )
        row.published_at = timezone.now()
        row.save(update_fields=["published_at"])
        released += 1
    return released


def _conflict(company: Company, crm_client_id: int, other_company_id: Optional[int]) -> Outcome:
    link, _ = PartnerCrmLink.objects.get_or_create(company=company)
    already = link.status == PartnerCrmStatus.CONFLICT and link.crm_client_id == crm_client_id
    link.status = PartnerCrmStatus.CONFLICT
    link.crm_client_id = crm_client_id
    link.conflict_company_id = other_company_id
    link.resolved_at = timezone.now()
    link.save()
    if not already:  # повтор того же ответа не задваивает ни журнал, ни уведомление
        _log(
            company,
            "partner.crm_conflict",
            "Клиент партнёра в CRM: конфликт сопоставления",
            f"Клиент CRM #{crm_client_id} уже сопоставлен другой компании ERP; ничего не переписано.",
            "WARNING",
            crm_client_id=crm_client_id,
            other_company_id=other_company_id,
        )
        _notify_conflict(company, crm_client_id, other_company_id)
    return Outcome(APPLIED, f"конфликт: клиент CRM #{crm_client_id}")


@transaction.atomic
def apply_client_resolved(data: Mapping[str, Any]) -> Outcome:
    """`crm.partner.client_resolved`: сопоставление клиента (linked) или состояние «конфликт» (conflict)."""
    erp_company_id = int(data["erp_company_id"])
    crm_client_id = int(data["crm_client_id"])
    status = str(data["status"])
    _advisory_lock(_LOCK_KIND, erp_company_id)

    company = Company.objects.filter(pk=erp_company_id).first()
    if company is None:
        logger.warning("partner client: company #%s is unknown, answer skipped", erp_company_id)
        return Outcome(SKIPPED_UNKNOWN_COMPANY, f"компания #{erp_company_id}")

    mapping = CrmClientMapping.objects.filter(company=company).first()
    if status == CONFLICT:
        if mapping is not None:
            # сопоставление появилось, пока шёл ответ (handoff из CRM): конфликт устарел
            return Outcome(SKIPPED_OTHER_CLIENT, f"компания уже сопоставлена клиенту CRM #{mapping.crm_client_id}")
        return _conflict(company, crm_client_id, _int_or_none(data.get("conflict_erp_company_id")))

    if mapping is not None and mapping.crm_client_id != crm_client_id:
        # компания уже сопоставлена другим клиентом CRM: молча не перепривязываем
        logger.warning(
            "partner client: company #%s is mapped to CRM client #%s, answer for #%s skipped",
            company.pk,
            mapping.crm_client_id,
            crm_client_id,
        )
        return Outcome(SKIPPED_OTHER_CLIENT, f"компания уже сопоставлена клиенту CRM #{mapping.crm_client_id}")
    created = mapping is None
    if created:
        holder = CrmClientMapping.objects.filter(crm_client_id=crm_client_id).first()
        if holder is not None:  # клиент CRM уже у другой компании ERP: тоже конфликт, не перепривязка
            return _conflict(company, crm_client_id, holder.company_id)
        mapping = CrmClientMapping.objects.create(crm_client_id=crm_client_id, company=company)

    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})[0]
    company.types.add(client_type)
    _map_contacts(company, list(data.get("contacts") or []))
    released = release_deferred_requests(company, crm_client_id)
    PartnerCrmLink.objects.filter(company=company).delete()  # состояние «linked» живёт в сопоставлении
    if created:
        _log(
            company,
            "partner.crm_linked",
            "Партнёр стал клиентом CRM",
            f"Клиент CRM #{crm_client_id} сопоставлен компании ({data.get('matched_by') or 'без пояснения'}); "
            f"заявок опубликовано: {released}.",
            crm_client_id=crm_client_id,
            released_requests=released,
        )
    return Outcome(APPLIED, f"клиент CRM #{crm_client_id}, заявок опубликовано: {released}")


def _int_or_none(value: Any) -> Optional[int]:
    return int(value) if value not in (None, "") else None


# ── Состояние для карточки ────────────────────────────────────────────────────────────────────────────────────────────


def crm_client_state(company: Company) -> Dict[str, Any]:
    """Что показать сотруднику: `linked` (сопоставление есть), `requested` (ждём CRM), `conflict`, `none` (не просили)."""
    mapping = CrmClientMapping.objects.filter(company=company).first()
    if mapping is not None:
        return {"status": LINKED, "crm_client_id": mapping.crm_client_id}
    link = PartnerCrmLink.objects.filter(company=company).first()
    if link is None:
        return {"status": NONE, "crm_client_id": None}
    if link.status == PartnerCrmStatus.CONFLICT:
        return {"status": CONFLICT, "crm_client_id": link.crm_client_id}
    return {"status": REQUESTED, "crm_client_id": None}

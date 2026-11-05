"""Партнёр становится клиентом CRM (PART-CRM, решение владельца 2026-11-04: «партнёр = клиент + «Мои товары»»).

CRM — источник правды по клиентам и контактам, поэтому ERP клиента не заводит, а просит CRM событием шины:

1. **Запрос.** Сотрудник приглашает партнёра в кабинет (`portal/desk/service.py`, `invite`): если компания не сопоставлена
   клиенту CRM (`CrmClientMapping`), в той же транзакции в outbox уходит `partner.client_requested` — реквизиты компании и
   контакты с e-mail (`request_client_in_crm`). Повторное приглашение, пока сопоставления нет, публикует его снова; CRM
   дедуплицирует по `erp_company_id` и id события. Откат приглашения (письмо не ушло) откатывает и событие.
2. **Ответ.** CRM находит клиента (по `erp_company_id`, ИНН, паре «страна + рег. номер») или создаёт и отвечает
   `crm.partner.client_resolved` (`apply_client_resolved`). Найденного по ключу чужого клиента CRM сама не привязывает
   (правила дублей Salesforce и HubSpot: совпадение по ключу — предложение слияния человеку, решение архитектора по PR #397):
   `linked` — клиент создан, найден по `erp_company_id` или подтверждён менеджером: ставится `CrmClientMapping`, компании
   добавляется тип `CLIENT` (кабинет даёт ей клиентские модули поверх партнёрских — роли складываются,
   `portal/services/access.py`), контакты сопоставляются с контактами CRM, заявки партнёра, созданные до сопоставления,
   публикуются (`DeferredRequestEvent`);
   `pending_confirmation` — найден похожий клиент без сопоставления, ждём менеджера CRM: ни сопоставления, ни `CLIENT`, заявки
   остаются отложенными;
   `conflict` — найденный клиент уже сопоставлен другой компании ERP: ничего не переписывается, состояние запоминается
   (`PartnerCrmLink`), ответственному за партнёра уходит уведомление.
   Если ERP не может принять `linked` (клиент CRM уже у другой компании ERP, а эта компания — у другого клиента), она не
   перепривязывает, а отвечает CRM событием `partner.client_rejected`: CRM снимает `erp_company_id` со своего клиента.
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
PENDING_CONFIRMATION = "pending_confirmation"
CONFLICT = "conflict"
NONE = "none"
HELD = "held"
UNVERIFIED = "unverified"

APPLIED = "applied"
SKIPPED_UNKNOWN_COMPANY = "skipped_unknown_company"
SKIPPED_OTHER_CLIENT = "skipped_other_client"
SKIPPED_NO_REQUEST = "skipped_no_request"

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


def lock_company(company_id: int) -> None:
    """Блокировка до конца транзакции: ответ CRM, заявка партнёра и передача из CRM по одной компании идут по очереди.

    Без неё заявка, созданная между проверкой сопоставления и записью `DeferredRequestEvent`, могла бы пережить ответ
    `linked` и остаться неопубликованной навсегда.
    """
    _advisory_lock(_LOCK_KIND, company_id)


def is_partner(company: Company) -> bool:
    return CompanyRelationship.objects.filter(company=company, role=RelationshipRole.PARTNER).exists()


def lock_if_partner(company: Company) -> None:
    """`lock_company` для компании с отношением `partner` (клиентов без отношения блокировка не касается)."""
    if is_partner(company):
        lock_company(company.pk)


def hold_for_verification(company: Company, crm_client_id: int) -> None:
    """Передача клиента из CRM нашла компанию партнёра по ИНН: сопоставление НЕ создаётся, заявки остаются отложенными.

    Инвариант PART-CRM: у партнёра `CrmClientMapping` появляется только после подтверждённой связи — ответа `linked` на
    запрос, отправленный после последнего «Пригласить», либо подтверждения менеджером в CRM. Состояние `held`,
    ответственному уходит уведомление; сотрудник сверяет ИНН и нажимает «Пригласить ещё раз» — запрос уходит в CRM, и
    дальше связь подтверждает менеджер CRM. Вызывать под `lock_company`.
    """
    link = PartnerCrmLink.objects.filter(company=company).first()
    already = link is not None and link.status == PartnerCrmStatus.HELD and link.crm_client_id == crm_client_id
    PartnerCrmLink.objects.update_or_create(
        company=company,
        defaults={
            "status": PartnerCrmStatus.HELD,
            "crm_client_id": crm_client_id,
            "conflict_company_id": None,
            "resolved_at": timezone.now(),
        },
    )
    if already:  # повтор передачи (ручной повтор в CRM) не задваивает ни журнал, ни уведомление
        return
    _log(
        company,
        "partner.crm_held",
        "Клиент партнёра в CRM: передача клиента удержана до сверки",
        f"Передача клиента #{crm_client_id} из CRM нашла компанию по ИНН; сопоставление не создано, заявки партнёра не "
        "выпускаются.",
        "WARNING",
        crm_client_id=crm_client_id,
    )
    _notify_unverified(company, crm_client_id)


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
    with transaction.atomic():  # внутри приглашения это та же транзакция; отдельно — своя
        PartnerCrmLink.objects.update_or_create(
            company=company,
            defaults={
                "status": PartnerCrmStatus.REQUESTED,
                "crm_client_id": None,
                "requested_at": timezone.now(),
                "resolved_at": None,
            },
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
        "Ничего не изменено, заявки партнёра остаются в ERP. Проверьте ИНН или рег. номер в карточке поставщика и у "
        "клиента в CRM, исправьте ошибочный и пригласите партнёра ещё раз."
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


def _notify_unverified(company: Company, crm_client_id: int) -> None:
    """Ответственному за партнёра (иначе администраторам): компанию связали с клиентом CRM по ИНН, заявки удержаны."""
    from notifications.services import notify_platform_admins, notify_user

    relationship = (
        CompanyRelationship.objects.filter(company=company, role=RelationshipRole.PARTNER)
        .select_related("responsible")
        .first()
    )
    title = f"Партнёр «{company.name}»: передача клиента из CRM удержана до сверки"
    message = (
        f"Передача клиента #{crm_client_id} из CRM нашла компанию партнёра по ИНН и была удержана: сопоставление не "
        "создано, заявки партнёра остаются в ERP и клиенту не уходят. Сверьте ИНН в карточке поставщика и у клиента в "
        "CRM, затем нажмите «Пригласить ещё раз»: запрос уйдёт в CRM, и связь подтвердит менеджер CRM. Заявка лида из "
        "передачи заведётся в ERP после подтверждения."
    )
    params = {"company": company.name, "crm_client_id": crm_client_id}
    code = "partner.crm_unverified"
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
    with transaction.atomic():
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


def _pending(company: Company, crm_client_id: int) -> Outcome:
    """CRM нашла похожего клиента без сопоставления и ждёт решения менеджера: состояние запоминается, ничего не привязывается."""
    link, _ = PartnerCrmLink.objects.get_or_create(company=company)
    already = link.status == PartnerCrmStatus.PENDING_CONFIRMATION and link.crm_client_id == crm_client_id
    link.status = PartnerCrmStatus.PENDING_CONFIRMATION
    link.crm_client_id = crm_client_id
    link.conflict_company_id = None
    link.resolved_at = timezone.now()
    link.save()
    if not already:
        _log(
            company,
            "partner.crm_pending",
            "Клиент партнёра в CRM: ждёт подтверждения менеджера",
            f"CRM нашла похожего клиента #{crm_client_id}; менеджер CRM подтверждает, та ли это компания. Заявки партнёра "
            "остаются в ERP и уйдут менеджеру после подтверждения.",
            crm_client_id=crm_client_id,
        )
    return Outcome(APPLIED, f"ждёт подтверждения: клиент CRM #{crm_client_id}")


def _reject(
    company: Company, crm_client_id: int, reason: str, other_id: Optional[int], *, other_is_company: bool
) -> Outcome:
    """ERP не принимает `linked`: клиент CRM уже у другой компании (или компания уже у другого клиента). Ничего не
    перепривязывается; CRM получает `partner.client_rejected` и снимает `erp_company_id`, сотрудник видит «конфликт»."""
    other_company_id = other_id if other_is_company else None
    with transaction.atomic():
        outcome = _conflict(company, crm_client_id, other_company_id)
        get_bus().publish(
            event_type_name("partner.client_rejected"),
            {
                "erp_company_id": company.pk,
                "crm_client_id": crm_client_id,
                "reason": reason,
                "other_erp_company_id": other_company_id,
                "actor": build_actor(actor_type="system"),
            },
            subject=f"company/{company.pk}",
        )
    return outcome


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
    if status == PENDING_CONFIRMATION:
        if mapping is not None:
            return Outcome(SKIPPED_OTHER_CLIENT, f"компания уже сопоставлена клиенту CRM #{mapping.crm_client_id}")
        return _pending(company, crm_client_id)

    if mapping is not None and mapping.crm_client_id != crm_client_id:
        # компания уже сопоставлена другим клиентом CRM: молча не перепривязываем
        logger.warning(
            "partner client: company #%s is mapped to CRM client #%s, answer for #%s skipped",
            company.pk,
            mapping.crm_client_id,
            crm_client_id,
        )
        return _reject(
            company, crm_client_id, "company_mapped_to_other_client", mapping.crm_client_id, other_is_company=False
        )
    created = mapping is None
    if created:
        link = PartnerCrmLink.objects.filter(company=company).first()
        if link is None or link.status not in (PartnerCrmStatus.REQUESTED, PartnerCrmStatus.PENDING_CONFIRMATION):
            # Инвариант PART-CRM: сопоставление партнёра — только по ответу на текущий запрос (связь в «запрошено» или
            # «ждёт подтверждения менеджера CRM»). Поздний ответ на старый запрос (после передачи клиента, конфликта)
            # ничего не создаёт и заявок не выпускает.
            state = link.status if link is not None else "нет запроса"
            _log(
                company,
                "partner.crm_linked_ignored",
                "Ответ CRM «клиент заведён» проигнорирован",
                f"Клиент CRM #{crm_client_id}: связь в состоянии «{state}», подтверждённого запроса нет. Сопоставление "
                "не создано, заявки партнёра не выпущены; нажмите «Пригласить ещё раз», если связь нужна.",
                "WARNING",
                crm_client_id=crm_client_id,
            )
            return Outcome(SKIPPED_NO_REQUEST, f"нет подтверждённого запроса ({state})")
        holder = CrmClientMapping.objects.filter(crm_client_id=crm_client_id).first()
        if holder is not None:  # клиент CRM уже у другой компании ERP: не перепривязываем, CRM снимет свою привязку
            return _reject(
                company, crm_client_id, "client_mapped_to_other_company", holder.company_id, other_is_company=True
            )
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
    """Что показать сотруднику: `linked` (сопоставление есть), `requested` (ждём CRM), `pending_confirmation` (ждём менеджера
    CRM), `conflict`, `none` (не просили)."""
    mapping = CrmClientMapping.objects.filter(company=company).first()
    if mapping is not None and mapping.verified_at is None and is_partner(company):
        # Сопоставление создала передача по совпадению ИНН: сотрудник подтверждает, та ли это компания.
        return {
            "status": UNVERIFIED,
            "crm_client_id": mapping.crm_client_id,
            "crm_client_name": mapping.crm_name or None,
            "inn": company.inn or None,
        }
    if mapping is not None:  # сопоставление партнёра появляется только после подтверждённой связи (PART-CRM)
        return {"status": LINKED, "crm_client_id": mapping.crm_client_id}
    link = PartnerCrmLink.objects.filter(company=company).first()
    if link is None:
        return {"status": NONE, "crm_client_id": None}
    if link.status == PartnerCrmStatus.PENDING_CONFIRMATION:
        return {"status": PENDING_CONFIRMATION, "crm_client_id": link.crm_client_id}
    if link.status == PartnerCrmStatus.HELD:
        return {"status": HELD, "crm_client_id": link.crm_client_id}
    if link.status == PartnerCrmStatus.CONFLICT:
        return {"status": CONFLICT, "crm_client_id": link.crm_client_id}
    return {"status": REQUESTED, "crm_client_id": None}


# ── Проверка сопоставления человеком ────────────────────────────────────────────────────────────────────────────────────


class NothingToVerify(Exception):
    """У компании нет непроверенного сопоставления (уже решили или не было)."""


def _unverified_mapping(company: Company) -> CrmClientMapping:
    mapping = CrmClientMapping.objects.select_for_update().filter(company=company, verified_at__isnull=True).first()
    if mapping is None:
        raise NothingToVerify()
    return mapping


@transaction.atomic
def confirm_unverified(company: Company, user: Any = None) -> int:
    """«Да, это та же компания»: сопоставление становится проверенным, заявки партнёра выпускаются, открывается CLIENT.

    Возвращает число выпущенных заявок. Право — как у приглашения (`supply.manage`, проверяет представление).
    """
    lock_company(company.pk)
    mapping = _unverified_mapping(company)
    mapping.verified_at = timezone.now()
    mapping.verified_by = user if getattr(user, "pk", None) else None
    mapping.save(update_fields=["verified_at", "verified_by", "updated_at"])
    client_type = CompanyType.objects.get_or_create(code="CLIENT", defaults={"name": "Клиент"})[0]
    company.types.add(client_type)
    released = release_deferred_requests(company, mapping.crm_client_id)
    PartnerCrmLink.objects.filter(company=company).delete()
    _log(
        company,
        "partner.crm_verified",
        "Партнёр стал клиентом CRM: сопоставление подтверждено сотрудником",
        f"Клиент CRM #{mapping.crm_client_id} подтверждён как та же компания; заявок опубликовано: {released}.",
        crm_client_id=mapping.crm_client_id,
        released_requests=released,
    )
    return released


@transaction.atomic
def reject_unverified(company: Company, user: Any = None) -> None:
    """«Нет, другая компания»: сопоставление снимается, CRM снимает `erp_company_id` у клиента, уходит обычный запрос.

    Контакты, созданные передачей из CRM в этой компании (они принадлежали клиенту CRM), уходят в архив, остальные только
    теряют сопоставление; ERP публикует `partner.client_rejected` (`rejected_by_staff`), затем — обычный запрос в CRM
    (`partner.client_requested`), и найденного клиента CRM подтверждает или отклоняет её менеджер.
    """
    from .crm_projections import archive_contact

    lock_company(company.pk)
    mapping = _unverified_mapping(company)
    crm_client_id = mapping.crm_client_id
    now = timezone.now()
    for link in CrmContactMapping.objects.select_related("contact").filter(contact__company=company):
        if link.contact.created_at >= mapping.created_at and link.contact.archived_at is None:
            archive_contact(link.contact, now)  # создан передачей: чужой человек в этой компании
        link.delete()
    mapping.delete()
    _log(
        company,
        "partner.crm_rejected",
        "Сопоставление с клиентом CRM отклонено сотрудником",
        f"Сотрудник решил, что клиент CRM #{crm_client_id} — другая компания: сопоставление снято, контакты передачи "
        "убраны, CRM снимет привязку. Партнёр запрашивается в CRM заново.",
        "WARNING",
        crm_client_id=crm_client_id,
    )
    get_bus().publish(
        event_type_name("partner.client_rejected"),
        {
            "erp_company_id": company.pk,
            "crm_client_id": crm_client_id,
            "reason": "rejected_by_staff",
            "other_erp_company_id": None,
            "actor": build_actor(user=user, actor_type="staff" if user is not None else "system"),
        },
        subject=f"company/{company.pk}",
    )
    request_client_in_crm(company, user)

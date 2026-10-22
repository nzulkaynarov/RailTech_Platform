"""Проекции ERP по событиям CRM на шине rt_bus (B3, L13, ADR-0015 п. 5, CONTRACTS §9).

Подписки ERP (`packages/contracts/bus/subscriptions.yaml`): `uz.railtech.crm.client.updated.v1` и
`uz.railtech.crm.contact.{created,updated,deleted}.v1`. События — снимки (event-carried state transfer) с `updated_at`
(`deleted_at` у удаления); порядок доставки не гарантирован, поэтому **более старый снимок уже применённого не применяется**
(`CrmProjectionState`). Повтор того же снимка — без действий.

Что обновляется. Только поля, которыми владеет CRM (ORCHESTRATOR §3 п. 16): у клиента — название компании (`Company.name`)
и ИНН (`Company.inn`), в ERP они только для чтения (`requisites.py`); у контакта — ФИО, должность, телефон, e-mail, Telegram,
язык, канал связи, признак основного. Прочие реквизиты (адрес, банк, МФО), финансы, права контакта в Cabinet (`can_act`),
приглашения и входы принадлежат ERP; в схеме `client.*.v1` остальных реквизитов нет (сегмент, `is_active` и ответственный
в проекцию компании не переносятся — полей в ERP нет). Контакт, созданный по событию, получает `can_act=False` (право действовать
не выдаётся молча — FIX-54).

Неизвестный клиент CRM (нет `CrmClientMapping`) — не ошибка: событие пропускается с записью в журнал (`skipped`), клиент
появится в ERP передачей (`POST /clients/handoff`). Контакт, удалённый в CRM, **архивируется, а не удаляется** (`Contact.archived_at`):
каскад стёр бы коды акцепта (`QuoteAcceptanceCode`) — след, по которому КП принято. Запись и связи (сделки, документы, коды,
сопоставление) остаются; `can_act=false`, Telegram отвязан, сессии портала и ссылки входа сняты, вход в Cabinet закрыт
(`active_contact_q`). Контакт, переехавший к другому клиенту CRM, переносится в компанию нового клиента, если она известна ERP.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional

from django.db import transaction
from django.utils.dateparse import parse_datetime
from parties.models import Company, Contact

from ..models import CrmClientMapping, CrmContactMapping, CrmProjectionKind, CrmProjectionState

logger = logging.getLogger(__name__)

APPLIED = "applied"
SKIPPED_STALE = "skipped_stale"
SKIPPED_UNKNOWN_CLIENT = "skipped_unknown_client"
SKIPPED_NO_CHANGE = "skipped_duplicate"


@dataclass(frozen=True)
class Outcome:
    """Итог обработки одного события: что сделано и почему; пишется в журнал."""

    status: str
    detail: str = ""

    @property
    def applied(self) -> bool:
        return self.status == APPLIED


def _moment(value: Any) -> datetime:
    moment = parse_datetime(str(value))
    if moment is None or moment.tzinfo is None:
        raise ValueError(f"метка времени {value!r} не RFC 3339 с поясом")
    return moment


def _state(kind: str, crm_id: int) -> Optional[CrmProjectionState]:
    return CrmProjectionState.objects.select_for_update().filter(kind=kind, crm_id=crm_id).first()


def _remember(kind: str, crm_id: int, applied_at: datetime, *, deleted: bool = False) -> None:
    CrmProjectionState.objects.update_or_create(
        kind=kind, crm_id=crm_id, defaults={"applied_at": applied_at, "deleted": deleted}
    )


def _log(outcome: Outcome, event_type: str, crm_id: int) -> Outcome:
    level = (
        logging.INFO
        if outcome.applied
        else logging.WARNING if outcome.status == SKIPPED_UNKNOWN_CLIENT else logging.INFO
    )
    logger.log(
        level,
        "rt_bus_projection %s #%s: %s %s",
        event_type,
        crm_id,
        outcome.status,
        outcome.detail,
        extra={"event_type": event_type, "crm_id": crm_id, "projection_status": outcome.status},
    )
    return outcome


# ── Клиент ────────────────────────────────────────────────────────────────────────────────────────────────────────────


@transaction.atomic
def apply_client_snapshot(data: Mapping[str, Any]) -> Outcome:
    """`client.updated`: название компании по `crm_client_id` (через `CrmClientMapping`)."""
    snapshot = data["client"]
    crm_client_id = int(snapshot["crm_client_id"])
    updated_at = _moment(snapshot["updated_at"])

    mapping = CrmClientMapping.objects.select_related("company").filter(crm_client_id=crm_client_id).first()
    if mapping is None:
        return _log(Outcome(SKIPPED_UNKNOWN_CLIENT, "клиент ещё не передан в ERP"), "client.updated", crm_client_id)

    state = _state(CrmProjectionKind.CLIENT, crm_client_id)
    if state is not None and state.applied_at >= updated_at:
        status = SKIPPED_NO_CHANGE if state.applied_at == updated_at else SKIPPED_STALE
        return _log(
            Outcome(status, f"применён снимок от {state.applied_at.isoformat()}"), "client.updated", crm_client_id
        )

    company: Company = mapping.company
    name = str(snapshot["name"]).strip()
    changed = []
    if name and company.name != name:
        company.name = name[: Company._meta.get_field("name").max_length]
        changed.append("name")
    inn = (snapshot.get("inn") or "").strip()
    if inn and company.inn != inn:
        if Company.objects.filter(inn=inn).exclude(pk=company.pk).exists():
            # ИНН уникален в ERP: чужая компания уже держит его — не ломаем снимок, запись в журнал для сотрудника.
            logger.warning(
                "rt_bus_projection client.updated #%s: ИНН уже у другой компании ERP, поле не применено", crm_client_id
            )
        else:
            company.inn = inn[: Company._meta.get_field("inn").max_length]
            changed.append("inn")
    if changed:
        company.save(update_fields=[*changed, "updated_at"])
    _remember(CrmProjectionKind.CLIENT, crm_client_id, updated_at)
    return _log(Outcome(APPLIED, f"компания #{company.pk}"), "client.updated", crm_client_id)


# ── Контакт ───────────────────────────────────────────────────────────────────────────────────────────────────────────

_CHANNELS = {"telegram", "email", "both"}
_LANGUAGES = {"ru", "uz", "en"}


def _contact_fields(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Поля ERP-контакта, которыми владеет CRM, из снимка."""
    fields: dict[str, Any] = {
        "name": str(snapshot["full_name"]).strip()[:255],
        "position": (snapshot.get("position") or "")[:255],
        "phone": (snapshot.get("phone_e164") or "")[:50],
        "email": (snapshot.get("email") or "")[:254],
        "is_primary": bool(snapshot.get("is_primary")),
    }
    if snapshot.get("language") in _LANGUAGES:
        fields["language"] = snapshot["language"]
    if snapshot.get("preferred_channel") in _CHANNELS:
        fields["preferred_channel"] = snapshot["preferred_channel"]
    return fields


def _telegram_fields(snapshot: Mapping[str, Any], contact: Optional[Contact]) -> dict[str, Any]:
    """Telegram контакта; чужой уже занятый `telegram_user_id` (уникален в ERP) не отбирается — запись в журнал."""
    telegram_id = snapshot.get("telegram_user_id")
    if telegram_id is None:
        return {"telegram_user_id": None, "telegram_username": ""} if contact is not None else {}
    clash = Contact.objects.filter(telegram_user_id=telegram_id)
    if contact is not None:
        clash = clash.exclude(pk=contact.pk)
    if clash.exists():
        logger.warning(
            "rt_bus_projection contact: Telegram %s уже у другого контакта ERP, поле не применено (CRM контакт #%s)",
            telegram_id,
            snapshot.get("crm_contact_id"),
        )
        return {}
    return {"telegram_user_id": telegram_id}


@transaction.atomic
def apply_contact_snapshot(data: Mapping[str, Any], event_type: str = "contact.updated") -> Outcome:
    """`contact.created` / `contact.updated`: проекция контакта по `crm_contact_id` (нет проекции — создаётся)."""
    snapshot = data["contact"]
    crm_contact_id = int(snapshot["crm_contact_id"])
    crm_client_id = int(snapshot["crm_client_id"])
    updated_at = _moment(snapshot["updated_at"])

    state = _state(CrmProjectionKind.CONTACT, crm_contact_id)
    if state is not None and state.applied_at >= updated_at:
        # Удалён позже снимка (надгробие) или снимок уже применён/старее — не применяем.
        status = SKIPPED_NO_CHANGE if state.applied_at == updated_at and not state.deleted else SKIPPED_STALE
        return _log(Outcome(status, f"применено до {state.applied_at.isoformat()}"), event_type, crm_contact_id)

    mapping = CrmContactMapping.objects.select_related("contact").filter(crm_contact_id=crm_contact_id).first()
    if mapping is not None:
        contact = mapping.contact
        fields = {**_contact_fields(snapshot), **_telegram_fields(snapshot, contact)}
        moved = _move_to_new_client(contact, crm_client_id, fields)
        _apply_primary(contact.company_id, contact.pk, fields)
        for key, value in fields.items():
            setattr(contact, key, value)
        if contact.archived_at is not None:
            contact.archived_at = (
                None  # более новый снимок после удаления: контакт вернулся (права и приглашение — заново)
            )
            fields["archived_at"] = None
        contact.save(update_fields=[*fields, "updated_at"])
        _remember(CrmProjectionKind.CONTACT, crm_contact_id, updated_at)
        return _log(
            Outcome(APPLIED, f"контакт #{contact.pk}" + (" перенесён в компанию нового клиента" if moved else "")),
            event_type,
            crm_contact_id,
        )

    client_mapping = CrmClientMapping.objects.select_related("company").filter(crm_client_id=crm_client_id).first()
    if client_mapping is None:
        return _log(
            Outcome(SKIPPED_UNKNOWN_CLIENT, f"клиент CRM #{crm_client_id} не передан в ERP"), event_type, crm_contact_id
        )

    company = client_mapping.company
    fields = {**_contact_fields(snapshot), **_telegram_fields(snapshot, None)}
    _apply_primary(company.pk, None, fields)
    contact = Contact.objects.create(company=company, can_act=False, **fields)
    CrmContactMapping.objects.create(crm_contact_id=crm_contact_id, contact=contact)
    _remember(CrmProjectionKind.CONTACT, crm_contact_id, updated_at)
    return _log(Outcome(APPLIED, f"контакт #{contact.pk} создан"), event_type, crm_contact_id)


def _move_to_new_client(contact: Contact, crm_client_id: int, fields: dict[str, Any]) -> bool:
    """Контакт теперь у другого клиента CRM: переносим в компанию этого клиента, если она известна ERP, иначе — запись в журнал.

    Старые сессии портала перестают действовать сами (сессия привязана к компании, `PortalAuthentication`); право действовать
    принадлежало прежней компании — в новой оно выдаётся заново. Основной контакт старой компании снимком не затрагивается.
    """
    target = CrmClientMapping.objects.filter(crm_client_id=crm_client_id).values_list("company_id", flat=True).first()
    if target is None:
        logger.warning(
            "rt_bus_projection contact: клиент CRM #%s контакта #%s не передан в ERP, контакт остался в прежней компании",
            crm_client_id,
            contact.pk,
        )
        return False
    if target == contact.company_id:
        return False
    contact.company_id = target
    contact.can_act = False
    fields["company"] = contact.company
    fields["can_act"] = False
    return True


def _apply_primary(company_id: int, contact_pk: Optional[int], fields: dict[str, Any]) -> None:
    """Основной контакт у компании один: снимок с `is_primary` снимает признак с остальных."""
    if fields.get("is_primary"):
        others = Contact.objects.filter(company_id=company_id, is_primary=True)
        if contact_pk is not None:
            others = others.exclude(pk=contact_pk)
        others.update(is_primary=False)


def archive_contact(contact: Contact, at: datetime) -> None:
    """Контакт удалён в CRM: в архив, не физически (каскад стёр бы `QuoteAcceptanceCode` — след акцепта КП).

    Запись, сделки, документы, коды акцепта и сопоставление остаются. Закрываем доступ: `can_act=false`, Telegram отвязан
    (уникальный id освобождается, вход по нему невозможен), сессии портала и ссылки входа сняты; вход по e-mail и приглашение
    отказывают архивному контакту (`active_contact_q`).
    """
    from portal.models import MagicLinkToken, PortalSession

    contact.archived_at = at
    contact.can_act = False
    contact.telegram_user_id = None
    contact.telegram_username = ""
    contact.save(update_fields=["archived_at", "can_act", "telegram_user_id", "telegram_username", "updated_at"])
    PortalSession.objects.filter(contact=contact).delete()
    MagicLinkToken.objects.filter(contact=contact).delete()


@transaction.atomic
def apply_contact_deleted(data: Mapping[str, Any]) -> Outcome:
    """`contact.deleted`: контакт архивируется в ERP (доступ в Cabinet закрывается), отметка не пускает поздние снимки."""
    crm_contact_id = int(data["crm_contact_id"])
    deleted_at = _moment(data["deleted_at"])

    state = _state(CrmProjectionKind.CONTACT, crm_contact_id)
    if state is not None and (state.applied_at > deleted_at or (state.deleted and state.applied_at == deleted_at)):
        status = SKIPPED_NO_CHANGE if state.deleted else SKIPPED_STALE
        return _log(Outcome(status, f"применено до {state.applied_at.isoformat()}"), "contact.deleted", crm_contact_id)

    mapping = CrmContactMapping.objects.select_related("contact").filter(crm_contact_id=crm_contact_id).first()
    detail = "проекции не было"
    if mapping is not None:
        archive_contact(mapping.contact, deleted_at)
        detail = f"контакт #{mapping.contact_id} в архиве"
    _remember(CrmProjectionKind.CONTACT, crm_contact_id, deleted_at, deleted=True)
    return _log(Outcome(APPLIED, detail), "contact.deleted", crm_contact_id)

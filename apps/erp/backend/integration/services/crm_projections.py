"""Проекции ERP по событиям CRM на шине rt_bus (B3, L13, ADR-0015 п. 5, CONTRACTS §9).

Подписки ERP (`packages/contracts/bus/subscriptions.yaml`): `uz.railtech.crm.client.updated.v1` и
`uz.railtech.crm.contact.{created,updated,deleted}.v1`. События — снимки (event-carried state transfer) с `updated_at`
(`deleted_at` у удаления); порядок доставки не гарантирован, поэтому **более старый снимок уже применённого не применяется**
(`CrmProjectionState`). Повтор того же снимка — без действий.

Что обновляется. Только поля, которыми владеет CRM: у клиента — название компании (`Company.name`); у контакта — ФИО,
должность, телефон, e-mail, Telegram, язык, канал связи, признак основного. Реквизиты и финансы (ИНН, адрес, банк, суммы)
принадлежат ERP и снимком CRM не перезаписываются; права контакта в Cabinet (`can_act`), приглашения и входы — тоже ERP, а
контакт, созданный по событию, получает `can_act=False` (право действовать не выдаётся молча — FIX-54).

Неизвестный клиент CRM (нет `CrmClientMapping`) — не ошибка: событие пропускается с записью в журнал (`skipped`), клиент
появится в ERP передачей (`POST /clients/handoff`). Контакт, удалённый в CRM, удаляется из ERP: сессии портала и ссылки входа
каскадно снимаются (доступ в Cabinet закрывается сразу), сделки и документы остаются без контакта (`SET_NULL`).
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
    if name and company.name != name:
        company.name = name[: Company._meta.get_field("name").max_length]
        company.save(update_fields=["name", "updated_at"])
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
        _apply_primary(contact.company_id, contact.pk, fields)
        for key, value in fields.items():
            setattr(contact, key, value)
        contact.save(update_fields=[*fields, "updated_at"])
        _remember(CrmProjectionKind.CONTACT, crm_contact_id, updated_at)
        return _log(Outcome(APPLIED, f"контакт #{contact.pk}"), event_type, crm_contact_id)

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


def _apply_primary(company_id: int, contact_pk: Optional[int], fields: dict[str, Any]) -> None:
    """Основной контакт у компании один: снимок с `is_primary` снимает признак с остальных."""
    if fields.get("is_primary"):
        others = Contact.objects.filter(company_id=company_id, is_primary=True)
        if contact_pk is not None:
            others = others.exclude(pk=contact_pk)
        others.update(is_primary=False)


@transaction.atomic
def apply_contact_deleted(data: Mapping[str, Any]) -> Outcome:
    """`contact.deleted`: контакт удаляется из ERP (доступ в Cabinet закрывается), надгробие не пускает поздние снимки."""
    crm_contact_id = int(data["crm_contact_id"])
    deleted_at = _moment(data["deleted_at"])

    state = _state(CrmProjectionKind.CONTACT, crm_contact_id)
    if state is not None and (state.applied_at > deleted_at or (state.deleted and state.applied_at == deleted_at)):
        status = SKIPPED_NO_CHANGE if state.deleted else SKIPPED_STALE
        return _log(Outcome(status, f"применено до {state.applied_at.isoformat()}"), "contact.deleted", crm_contact_id)

    mapping = CrmContactMapping.objects.select_related("contact").filter(crm_contact_id=crm_contact_id).first()
    detail = "проекции не было"
    if mapping is not None:
        contact_pk = mapping.contact_id
        mapping.contact.delete()  # сессии и ссылки входа — каскадом; mapping уходит вместе с контактом
        detail = f"контакт #{contact_pk} удалён"
    _remember(CrmProjectionKind.CONTACT, crm_contact_id, deleted_at, deleted=True)
    return _log(Outcome(APPLIED, detail), "contact.deleted", crm_contact_id)

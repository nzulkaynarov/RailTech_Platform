"""Сборка тела событий ERP для шины rt_bus (B3): `DealRef`, `Actor`, ссылки на контакты, поле `data` конверта.

Чистые функции без публикации: что и когда публиковать, решает сервисный слой (`events.py`, `document_events.py`).
Состав `data` — прежнее тело вебхука без `version`, `event`, `occurred_at` (они в конверте): `erp_company_id`, `crm_client_id`,
`deal` (`DealRef`), `actor`, `payload`; схемы — `packages/contracts/events/erp/`.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Union

from django.conf import settings
from django.utils import timezone

from ..models import CrmClientMapping, CrmContactMapping, CrmUserMapping
from . import stages

logger = logging.getLogger(__name__)

#: Короткие имена 25 типов ERP (`<сущность>.<действие>`); полный тип — `uz.railtech.erp.<имя>.v1`. `quote.ready_for_approval`
#: адресован EDS (EDS-03) и CRM не доставляется (`bus/subscriptions.yaml`).
VALID_EVENT_TYPES = {
    "request.created",
    "deal.stage_changed",
    "quote.sent",
    "quote.viewed",
    "quote.accepted",
    "quote.rejected",
    "quote.acceptance_code_requested",
    "quote.ready_for_approval",
    "contract.signed",
    "contract.status_changed",
    "invoice.issued",
    "invoice.paid",
    "invoice.overdue",
    "delivery.status_changed",
    "delivery.eta_changed",
    "act.issued",
    "act.accepted",
    "act.returned",
    "deal.won",
    "deal.lost",
    "document.created",
    "invite.sent",
    "invite.requested",
    "delivery.line_accepted",
    "delivery.line_disputed",
}

EVENT_TYPE_PREFIX = "uz.railtech.erp."
EVENT_TYPE_SUFFIX = ".v1"


def event_type_name(short: str) -> str:
    """`quote.sent` → `uz.railtech.erp.quote.sent.v1`; неизвестное короткое имя — ошибка вызывающего кода."""
    if short not in VALID_EVENT_TYPES:
        raise ValueError(f"Неизвестный тип события ERP: {short!r}")
    return f"{EVENT_TYPE_PREFIX}{short}{EVENT_TYPE_SUFFIX}"


def _format_amount(value: Optional[Union[str, Decimal]]) -> Optional[str]:
    """Контракт `Amount`: строка с двумя знаками; `None` — суммы нет."""
    return None if value is None else f"{Decimal(str(value)):.2f}"


def _check_stage(stage: Any) -> str:
    """Стадия в событии — только код `DealStage` контракта; всё остальное — ошибка вызывающего кода."""
    if not stages.is_deal_stage(stage):
        raise ValueError(f"Стадия {stage!r} не из контракта шва (DealStage): {', '.join(stages.DEAL_STAGES)}")
    return stage


def build_deal_ref(deal: Any) -> Dict[str, Any]:
    """Формирует объект `DealRef` тела события (`events/erp/_defs.v1.json`).

    Стадия и сумма — из `stages.py`, как в ответах integration: сумма — последняя версия КП, видимая клиенту,
    иначе `null` (черновики в сумму сделки не входят). Словарь на входе — уже готовая проекция (`stage` — код
    `DealStage`, `amount` — строка либо `None`).
    """
    if isinstance(deal, dict):
        erp_deal_id = int(deal["erp_deal_id"])
        return {
            "erp_deal_id": erp_deal_id,
            "number": str(deal.get("number") or f"D-{erp_deal_id}"),
            "title": str(deal.get("title") or f"Сделка #{erp_deal_id}"),
            "stage": _check_stage(deal.get("stage")),
            "amount": _format_amount(deal.get("amount")),
            "currency": str(deal.get("currency", "UZS")).upper(),
        }

    # Django Deal Model: номер ЗВ/ПР выдаёт ERP (ERP-09); сделка без номера (не сохранена) — прежний `D-<id>`.
    erp_deal_id = deal.id
    return {
        "erp_deal_id": erp_deal_id,
        "number": getattr(deal, "number", "") or f"D-{erp_deal_id}",
        "title": deal.title or f"Сделка #{erp_deal_id}",
        "stage": stages.deal_stage(deal),
        "amount": _format_amount(stages.deal_amount(deal)),
        "currency": stages.deal_currency(deal),
    }


def build_actor(
    user: Optional[Any] = None,
    actor_type: Optional[str] = None,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """Формирует объект `Actor` тела события."""
    if actor_type is None:
        if user is None:
            actor_type = "system"
        elif getattr(user, "is_portal_user", False):
            actor_type = "client"
        else:
            actor_type = "staff"

    if actor_type not in ("system", "staff", "client"):
        actor_type = "system"

    actor: Dict[str, Any] = {"type": actor_type}
    if name:
        actor["name"] = name
    elif user:
        user_name = ""
        if hasattr(user, "get_full_name"):
            user_name = user.get_full_name()
        if not user_name:
            user_name = getattr(user, "name", "") or getattr(user, "username", "")
        if user_name:
            actor["name"] = user_name

    return actor


def client_actor(contact: Optional[Any]) -> Dict[str, Any]:
    """Действующее лицо — клиент из Cabinet (контакт портала); без имени — просто `client`."""
    return build_actor(actor_type="client", name=getattr(contact, "name", None) or None)


def build_event_data(
    erp_company_id: int,
    payload: Dict[str, Any],
    deal: Optional[Any] = None,
    actor: Optional[Dict[str, Any]] = None,
    crm_client_id: Optional[int] = None,
    event_type: str = "",
) -> Optional[Dict[str, Any]]:
    """Собирает поле `data` конверта. Нет сопоставления компании с клиентом CRM и `crm_client_id` не передан — `None`.

    CRM принимает только события привязанных клиентов, поэтому для компании без `CrmClientMapping` события нет.
    """
    if crm_client_id is None:
        mapping = CrmClientMapping.objects.filter(company_id=erp_company_id).first()
        if not mapping:
            logger.info(
                "Событие %s не публикуется: компания #%s не сопоставлена клиенту CRM", event_type, erp_company_id
            )
            return None
        crm_client_id = mapping.crm_client_id

    data: Dict[str, Any] = {
        "erp_company_id": int(erp_company_id),
        "crm_client_id": int(crm_client_id),
        "actor": actor or {"type": "system"},
        "payload": payload,
    }
    if deal is not None:
        data["deal"] = build_deal_ref(deal)
    return data


def _aware(moment: Optional[Any]) -> Optional[datetime]:
    if moment is None:
        return None
    if timezone.is_naive(moment):
        return timezone.make_aware(moment)
    return moment


def _cabinet_url() -> str:
    """Адрес Cabinet из настроек (`CABINET_URL`), без хвостового слэша: ссылки событий не зашивают прод-домен."""
    return getattr(settings, "CABINET_URL", "http://cabinet.localhost").rstrip("/")


_INN = re.compile(r"^\d{9,14}$")


def _user_name(user: Any) -> str:
    name = user.get_full_name() if hasattr(user, "get_full_name") else ""
    return (name or getattr(user, "email", "") or "").strip()


def _crm_user_id(user: Optional[Any]) -> Optional[int]:
    if user is None:
        return None
    return CrmUserMapping.objects.filter(user=user).values_list("crm_user_id", flat=True).first()


def request_parties(deal: Any, manager_crm_user_id: Optional[int] = None) -> Dict[str, Any]:
    """Отправитель и менеджер заявки для `request.created` (C1-G-7, решение 2026-10-26; поля необязательные, L8).

    Отправитель — компания сделки (название, ИНН — только похожий на ИНН) и контакт: офлайн-контакт сделки, представитель
    клиента или основной контакт компании. Менеджер — `manager_crm_user_id` вызывающего (ответственный передачи из CRM),
    иначе ответственный сделки ERP (`assigned_to`, затем `manager`) с сопоставлением CRM. Чего нет — того поля нет.
    """
    parties: Dict[str, Any] = {}
    company = getattr(deal, "company", None)
    if company is not None:
        name = (company.name or "").strip()
        if name:
            parties["company_name"] = name[:300]
        inn = (company.inn or "").strip()
        if _INN.match(inn):
            parties["company_inn"] = inn
    contact = getattr(deal, "contact", None)
    client = getattr(deal, "client", None)
    if contact is None and company is not None:
        contact = company.contacts.filter(is_primary=True).first() or company.contacts.first()
    contact_name = (contact.name if contact is not None else _user_name(client) if client is not None else "").strip()
    if contact_name:
        parties["contact_name"] = contact_name[:255]
    if manager_crm_user_id is None:
        manager_crm_user_id = _crm_user_id(getattr(deal, "assigned_to", None)) or _crm_user_id(
            getattr(deal, "manager", None)
        )
    if manager_crm_user_id:
        parties["manager_crm_user_id"] = int(manager_crm_user_id)
    return parties


def contact_refs(contact: Any) -> Dict[str, Any]:
    """`erp_contact_id` и `crm_contact_id` контакта для тела события (CRM-идентификатор — `null`, если не сопоставлен)."""
    crm_contact_id = CrmContactMapping.objects.filter(contact=contact).values_list("crm_contact_id", flat=True).first()
    return {"erp_contact_id": contact.id, "crm_contact_id": crm_contact_id}

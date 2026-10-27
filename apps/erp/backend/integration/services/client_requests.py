"""«Создать заявку» CRM для клиента, уже переданного в ERP (`POST /clients/{crm_client_id}/requests`, шов 0.9.0, CRM-03).

SPEC-v3 §3.1 шаг 2: менеджер создаёт заявку из лида или карточки клиента — ERP заводит сделку процесса `v3` (ERP-07) в
стадии FSM `DRAFT` с номером `ЗВ-ГГГГ-NNN` (ERP-09, `Deal.save`), срочностью и менеджером заявки — владельцем сделки
(B-008), и в той же транзакции публикует `request.created(source=crm)`: EDS регистрирует письмо директору со срочностью и
файлом письма (`letter_file_id`), CRM связывает событие со своей заявкой по `crm_request_id`.

* Идемпотентно по `crm_request_id` (`Deal.crm_request_id` уникален): повтор — та же заявка, 200, без второго события;
  параллельные повторы сериализует транзакционная блокировка по `crm_request_id`.
* Клиент без сопоставления `crm_client_id` — `CLIENT_NOT_FOUND` (404): CRM сначала передаёт клиента (`/clients/handoff`).
* Контакт заявки — сопоставленный по `crm_contact_id`; незнакомый ERP контакт создаётся в компании с сопоставлением, как
  в передаче (`handoff._create_contacts`). Нет контакта — основной контакт компании. E-mail не обязателен.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from django.db import transaction
from portal.models import PortalRequestLine

from crm.models import Deal

from ..exceptions import IntegrationNotFound
from ..models import CrmClientMapping, CrmContactMapping, CrmUserMapping
from . import events, stages
from .handoff import _advisory_lock, _create_contacts

logger = logging.getLogger(__name__)

CLIENT_NOT_FOUND = "CLIENT_NOT_FOUND"


def manager_for(crm_user_id: Optional[int]):
    """Сотрудник ERP — менеджер заявки CRM (B-008): по сопоставлению провижининга; нет — сделка без менеджера."""
    if not crm_user_id:
        return None
    mapping = CrmUserMapping.objects.filter(crm_user_id=crm_user_id).select_related("user").first()
    return mapping.user if mapping else None


def _response(deal: Deal) -> Dict[str, Any]:
    return {"erp_company_id": deal.company_id, "erp_request_id": deal.pk, "number": deal.number}


def _contact(company, data: Dict[str, Any]):
    item = data.get("contact")
    if not item:
        return company.contacts.filter(is_primary=True).first() or company.contacts.first()
    mapping = CrmContactMapping.objects.filter(crm_contact_id=item["crm_contact_id"]).select_related("contact").first()
    if mapping is not None and mapping.contact is not None and mapping.contact.company_id == company.id:
        return mapping.contact
    _, primary = _create_contacts(company, {"company": {"language": company.language}, "contacts": [item]})
    return primary


def create_client_request(crm_client_id: int, data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Заявка клиента из CRM. Возвращает (ответ, создана ли новая)."""
    with transaction.atomic():
        _advisory_lock("request", data["crm_request_id"])
        existing = Deal.objects.filter(crm_request_id=data["crm_request_id"]).first()
        if existing is not None:
            return _response(existing), False
        mapping = CrmClientMapping.objects.filter(crm_client_id=crm_client_id).select_related("company").first()
        if mapping is None:
            raise IntegrationNotFound(CLIENT_NOT_FOUND)
        company = mapping.company
        owner = data["owner"]
        summary = data["need"]["summary"].strip()
        deal = Deal(
            company=company,
            contact=_contact(company, data),
            manager=manager_for(owner.get("crm_user_id")),
            stage=stages.initial_fsm_stage(),
            title=f"Заявка: {company.name}",
            notes=summary,
            process="v3",
            urgency=data["urgency"],
            crm_request_id=data["crm_request_id"],
        )
        deal.save()
        for idx, text in enumerate(data["need"].get("product_interest") or []):
            PortalRequestLine.objects.create(deal=deal, text=str(text).strip(), sort_order=idx + 1)
        letter_file_id = data.get("letter_file_id")
        events.publish_request_created(
            deal,
            source="crm",
            erp_request_id=deal.id,
            summary=summary,
            actor=events.build_actor(actor_type="staff", name=owner.get("name")),
            crm_client_id=crm_client_id,
            manager_crm_user_id=owner.get("crm_user_id"),
            letter_file_id=str(letter_file_id) if letter_file_id else None,
            crm_request_id=data["crm_request_id"],
        )
        logger.info("CRM request #%s → deal #%s %s", data["crm_request_id"], deal.id, deal.number)
        return _response(deal), True

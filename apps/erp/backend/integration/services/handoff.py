"""Handoff service: передача клиента и заявки из CRM в ERP (CONTRACTS §2, M3-ERP-01).

Идемпотентно по `crm_client_id`:
- Повторный вызов возвращает 200 и существующие erp_company_id, erp_request_id.
- Первый вызов создаёт компанию, контакты, заявку (при create_request: true),
  генерирует и отправляет инвайт в Cabinet, возвращает 201.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Tuple

from django.conf import settings
from django.db import transaction
from parties.models import Company, CompanyType, Contact
from portal.models import PortalRequestLine
from portal.services.invitation import invite_contact_to_portal

from crm.models import Deal

from ..models import CrmClientMapping, CrmContactMapping
from . import stages

logger = logging.getLogger(__name__)


@transaction.atomic
def process_client_handoff(data: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """Обработка handoff клиента из CRM в ERP.

    Возвращает (response_data, created).
    """
    crm_client_id = data["crm_client_id"]

    # Проверка идемпотентности по crm_client_id
    existing_mapping = CrmClientMapping.objects.filter(crm_client_id=crm_client_id).select_related("company").first()
    if existing_mapping:
        company = existing_mapping.company
        existing_deal = company.deals.order_by("created_at").first()
        primary_contact = company.contacts.filter(is_primary=True).first() or company.contacts.first()

        cabinet_url = getattr(settings, "CABINET_URL", "http://cabinet.localhost")
        channels = data.get("invite", {}).get("channels", ["email"])

        return {
            "erp_company_id": company.id,
            "erp_request_id": existing_deal.id if existing_deal else None,
            "invite": {
                "sent_via": channels,
                "cabinet_url": cabinet_url,
            },
        }, False

    # Создание новой компании
    c_data = data["company"]
    company_name = c_data["name"].strip()
    inn = (c_data.get("inn") or "").strip() or None
    language = c_data.get("language") or "ru"

    company = Company.objects.create(
        name=company_name,
        inn=inn,
        stated_inn=inn or "",
        language=language,
        is_registered=True,
    )

    client_type = CompanyType.objects.filter(code="CLIENT").first()
    if client_type:
        company.types.add(client_type)

    # Создание контактов и сопоставлений
    contacts_list = []
    primary_contact = None
    for contact_item in data["contacts"]:
        phone = (contact_item.get("phone") or "").strip()
        email = (contact_item.get("email") or "").strip().lower()
        telegram_user_id = contact_item.get("telegram_user_id")
        is_primary = contact_item.get("is_primary", False)
        preferred_channel = contact_item.get("preferred_channel", "both")
        c_lang = contact_item.get("language") or language

        contact = Contact.objects.create(
            company=company,
            name=contact_item["name"].strip(),
            phone=phone,
            email=email,
            telegram_user_id=telegram_user_id,
            language=c_lang,
            is_primary=is_primary,
            preferred_channel=preferred_channel,
            can_act=True,
        )

        CrmContactMapping.objects.create(
            crm_contact_id=contact_item["crm_contact_id"],
            contact=contact,
        )
        contacts_list.append(contact)
        if is_primary or primary_contact is None:
            primary_contact = contact

    if not primary_contact and contacts_list:
        primary_contact = contacts_list[0]

    # Создание заявки, если запрошено
    erp_request_id = None
    if data.get("create_request"):
        deal = Deal.objects.create(
            company=company,
            contact=primary_contact,
            stage=stages.initial_fsm_stage(),  # DRAFT, как у заявки из портала; стадия контракта — `request`
            title=f"Заявка: {company.name}",
            notes=data["need"]["summary"],
        )
        erp_request_id = deal.pk

        # Создание строк спецификации заявки
        product_interest = data["need"].get("product_interest") or []
        for idx, item_text in enumerate(product_interest):
            PortalRequestLine.objects.create(
                deal=deal,
                text=str(item_text).strip(),
                sort_order=idx + 1,
            )

    # Отправка инвайта в личный кабинет
    invite_channels = data.get("invite", {}).get("channels", ["email"])
    effective_channel = "both" if len(invite_channels) > 1 else (invite_channels[0] if invite_channels else "email")

    # В CRM уходит адрес кабинета без токена: рабочая ссылка входа есть только в письме клиента (FIX-14).
    cabinet_url = getattr(settings, "CABINET_URL", "http://cabinet.localhost")
    if primary_contact:
        invite_contact_to_portal(
            contact=primary_contact,
            channel=effective_channel,
            language=primary_contact.language,
        )

    # Сохраняем маппинг CRM клиента
    CrmClientMapping.objects.create(
        crm_client_id=crm_client_id,
        company=company,
    )

    return {
        "erp_company_id": company.id,
        "erp_request_id": erp_request_id,
        "invite": {
            "sent_via": invite_channels,
            "cabinet_url": cabinet_url,
        },
    }, True

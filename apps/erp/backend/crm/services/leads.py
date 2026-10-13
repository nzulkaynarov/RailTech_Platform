"""
Лид: площадка МАРШРУТИЗИРУЕТ, сделку создаёт принимающая сторона.

Замер 24-08: единственное действие экрана «Лиды» — «Конвертировать в сделку» — у штатного
оператора всегда отказывало (`ADMIN_VIEWER_CANNOT_ACT`), а проходило только у суперпользователя,
которому ADR-0001 бизнес-операции запрещает. Экран был отгружен и на 100 % нефункционален.

**Эталон — Salesforce Lead Queue + Take Ownership** (он же PRM Lead Inbox): входящий лид лежит
в очереди, площадка его квалифицирует и назначает владельцу, а запись в работу берёт
принимающая сторона — она же становится владельцем созданного объекта. Odoo и HubSpot устроены
так же: квалификация отделена от конвертации.

Salesforce ДОПУСКАЕТ и конвертацию лида самим админом — но только при явно названном владельце
и с отдельным правом. Наш ADR-0002 строже: оператор не создаёт бизнес-объект, принадлежащий
арендатору. Поэтому гард `is_platform_admin_viewer` в `convert_lead_to_deal` **остаётся** — он
был прав; недоставало второй половины механики, а не разрешения.
"""

import logging
from typing import Optional, Tuple

from django.db import transaction
from django.utils import timezone

from accounts.models import Company, CustomUser

from ..models import ActivityLog, Lead

logger = logging.getLogger(__name__)


def find_similar_leads(lead: Lead, limit: int = 5) -> list[Lead]:
    """Похожие лиды по e-mail и телефону (Odoo «Similar Leads»).

    Публичная форма лендинга открыта без аутентификации, поэтому поток дублей ожидаем по
    построению: показывать их надо ДО назначения, иначе одна и та же заявка уедет в две
    компании.
    """
    from django.db.models import Q

    similar = Lead.objects.exclude(pk=lead.pk)
    conditions = Q()
    if lead.email:
        conditions |= Q(email__iexact=lead.email)
    if lead.phone:
        conditions |= Q(phone=lead.phone)
    if not conditions:
        return []
    return list(similar.filter(conditions).order_by("-created_at")[:limit])


@transaction.atomic
def route_lead_to_company(
    lead: Lead,
    operator: CustomUser,
    company: Optional[Company],
    reason: str = "",
) -> Tuple[Optional[Lead], Optional[str]]:
    """Оператор платформы назначает лид компании (Salesforce: lead assignment).

    Это МОДЕРАЦИЯ и МАРШРУТИЗАЦИЯ, а не действие от лица арендатора: платформа не создаёт
    сделку и не становится её владельцем — она лишь передаёт запрос тому, кто им займётся.
    """
    if not getattr(operator, "is_platform_admin", False):
        return None, "PLATFORM_OPERATOR_REQUIRED"
    if company is None:
        return None, "COMPANY_NOT_FOUND"
    if not company.is_active:
        return None, "COMPANY_ARCHIVED"
    if lead.is_processed:
        return None, "LEAD_ALREADY_PROCESSED"
    clean_reason = (reason or "").strip()
    if not clean_reason:
        return None, "REASON_REQUIRED"

    lead.owner_company = company
    lead.assigned_at = timezone.now()
    lead.assigned_by = operator
    lead.rejection_reason = ""
    lead.save(update_fields=["owner_company", "assigned_at", "assigned_by", "rejection_reason"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="lead",
        entity_id=lead.id,
        action="Лид назначен компании",
        detail=f"Лид #{lead.id} ({lead.email}) → {company.name}",
        # Префикс `admin.` — по нему «Журнал доступа» отбирает операторские действия.
        event_code="admin.lead.routed",
        event_params={"lead_id": lead.id, "company_name": company.name},
        actor=operator,
        reason=clean_reason,
        level="INFO",
        company_id=company.id,
    )
    return lead, None


@transaction.atomic
def reject_lead(lead: Lead, operator: CustomUser, reason: str = "") -> Tuple[Optional[Lead], Optional[str]]:
    """Спам или дубль: лид закрывается площадкой с причиной, без создания сделки."""
    if not getattr(operator, "is_platform_admin", False):
        return None, "PLATFORM_OPERATOR_REQUIRED"
    if lead.is_processed:
        return None, "LEAD_ALREADY_PROCESSED"
    clean_reason = (reason or "").strip()
    if not clean_reason:
        return None, "REASON_REQUIRED"

    lead.is_processed = True
    lead.rejection_reason = clean_reason
    lead.save(update_fields=["is_processed", "rejection_reason"])

    from core.audit import log_admin_action

    log_admin_action(
        entity_type="lead",
        entity_id=lead.id,
        action="Лид отклонён",
        detail=f"Лид #{lead.id} ({lead.email}): {clean_reason}",
        event_code="admin.lead.rejected",
        event_params={"lead_id": lead.id},
        actor=operator,
        reason=clean_reason,
        level="WARNING",
    )
    return lead, None


@transaction.atomic
def claim_lead(lead: Lead, actor: CustomUser) -> Tuple[Optional[object], Optional[str]]:
    """Компания берёт назначенный ей лид в работу — и становится владельцем сделки.

    Второй шаг механики: платформа передала запрос, арендатор его принял. Именно здесь
    рождается бизнес-объект, и владелец у него правильный — компания, а не оператор.
    """
    from accounts.services import is_platform_admin_viewer

    if is_platform_admin_viewer(actor):
        return None, "ADMIN_VIEWER_CANNOT_ACT"
    if lead.owner_company_id is None:
        return None, "LEAD_NOT_ROUTED"
    if lead.is_processed:
        return None, "LEAD_ALREADY_PROCESSED"
    is_member = actor.memberships.filter(company_id=lead.owner_company_id, is_active=True).exists()
    if not is_member:
        return None, "LEAD_NOT_YOURS"

    from ..constants import DealStageCode
    from ..models import Deal, DealStage

    deal = Deal.objects.create(
        company=lead.owner_company,
        client=CustomUser.objects.filter(email__iexact=lead.email).first(),
        manager=actor,
        # `.get`, а не `.first()`: справочник стадий сеется миграцией (Rule 1), и молчаливый
        # None означал бы сделку без стадии — она не попала бы ни в одну витрину.
        stage=DealStage.objects.get(code=DealStageCode.DRAFT),
        title=(lead.message[:200] if lead.message else f"Лид: {lead.name}"),
        notes=f"Создано из лида #{lead.id}\nEmail: {lead.email}\nТелефон: {lead.phone}",
    )

    lead.is_processed = True
    lead.converted_deal = deal
    lead.converted_at = timezone.now()
    lead.save(update_fields=["is_processed", "converted_deal", "converted_at"])

    ActivityLog.objects.create(
        action="Лид взят в работу",
        detail=f"Лид #{lead.id} → сделка #{deal.id}",
        user=actor,
        level="SUCCESS",
        deal=deal,
        company=lead.owner_company,
        event_code="lead.claimed",
        event_params={"lead_id": lead.id, "deal_id": deal.id},
    )
    return deal, None

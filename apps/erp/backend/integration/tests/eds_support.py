"""Помощники тестов волны 12 (EDS-01, EDS-03): резолюция с исполнителями расчёта и решение директора из маршрута EDS."""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.utils import timezone
from integration.models import CrmUserMapping

from crm.services import calc_tasks
from crm.services.eds_quote_approval import apply_director_decision


def assign_calc(deal, *assignees, letter_id: uuid.UUID | None = None, margin=None):
    """Резолюция EDS по сделке: `assignees` — (пользователь ERP | None, crm_user_id, зона). Пользователь сопоставляется с
    `crm_user_id` (`CrmUserMapping`), как после провижининга CRM. Повторный вызов по тому же письму — новая резолюция.
    """
    for user, crm_user_id, _zone in assignees:
        if user is not None:
            CrmUserMapping.objects.get_or_create(user=user, defaults={"crm_user_id": crm_user_id})
    return calc_tasks.apply_resolution(
        deal,
        eds_letter_id=letter_id or uuid.uuid5(uuid.NAMESPACE_URL, f"letter-{deal.pk}"),
        letter_number="ВХ-104/26",
        letter_subject="Запрос КП",
        text="Подготовить расчёт и КП",
        due=timezone.localdate() + timedelta(days=3),
        min_margin_pct=margin,
        decided_by_crm_user_id=3,
        decided_by_name="Директор",
        decided_at=timezone.now(),
        assignees=[calc_tasks.Assignment(crm_user_id, zone) for _user, crm_user_id, zone in assignees],
    ).task


def _decide(quote, decision: str, route_status: str, *, comment=None, outgoing_number=None, channels=None) -> str:
    quote.refresh_from_db()
    return apply_director_decision(
        erp_quote_id=quote.pk,
        quote_version=quote.eds_revision,
        decision=decision,
        route_status=route_status,
        comment=comment,
        outgoing_number=outgoing_number,
        channels=channels if decision == "approve" else None,
        decided_by={"crm_user_id": 3, "full_name": "Директор"},
        decided_at=timezone.now(),
    )


def approve_in_eds(quote, outgoing_number: str = "ИСХ-001/26", channels=None) -> str:
    """Директор одобрил текущую редакцию КП в EDS: ИСХ-номер на КП, «Готово к отправке». С каналами — ERP сразу
    отправляет КП клиенту по доступным из них (ERP-11); без каналов (по умолчанию) — отправляет менеджер (C1-G-4)."""
    return _decide(quote, "approve", "approved", outgoing_number=outgoing_number, channels=channels)


def return_in_eds(quote, comment: str = "На доработку") -> str:
    """Директор вернул текущую редакцию КП на доработку: КП в черновике с комментарием."""
    return _decide(quote, "return", "returned", comment=comment)

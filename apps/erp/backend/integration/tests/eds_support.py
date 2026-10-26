"""Помощники тестов EDS-03: решение директора из маршрута EDS для КП, ждущего одобрения (как обработчик `approval.decided`)."""

from __future__ import annotations

from django.utils import timezone

from crm.services.eds_quote_approval import apply_director_decision


def approve_in_eds(quote, outgoing_number: str = "ИСХ-001/26", decided_by_crm_user_id: int = 3) -> str:
    """Директор одобрил текущую редакцию КП в EDS: ИСХ-номер на КП, «Готово к отправке»."""
    quote.refresh_from_db()
    return apply_director_decision(
        erp_quote_id=quote.pk,
        quote_version=quote.eds_revision,
        decision="approve",
        route_status="approved",
        comment=None,
        outgoing_number=outgoing_number,
        channels=["cabinet"],
        decided_by={"crm_user_id": decided_by_crm_user_id, "full_name": "Директор"},
        decided_at=timezone.now(),
    )

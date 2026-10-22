"""Шины, которые обслуживают тестовые view Django (подменяются фикстурами)."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.http import HttpRequest, JsonResponse

from rt_bus.django.bus import DjangoBus

RECEIVER: list[DjangoBus] = []
PUBLISHER: list[DjangoBus] = []


def bus_for_view() -> DjangoBus:
    return RECEIVER[-1]


def win_deal(request: HttpRequest) -> JsonResponse:
    """Бизнес-view ERP: изменение и событие в одной транзакции."""
    from tests.conftest import example_data

    data: dict[str, Any] = example_data("erp/deal.won.v1")
    with transaction.atomic():
        event = PUBLISHER[-1].publish("uz.railtech.erp.deal.won.v1", data)
    return JsonResponse({"event_id": event.id})

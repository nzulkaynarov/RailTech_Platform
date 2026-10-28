"""Обработчики входящих событий шины rt_bus в ERP (B3, L13): проекции данных клиента CRM и решения директора в EDS.

Регистрируются в реестре по умолчанию при загрузке приложения (`IntegrationConfig.ready`); вызываются задачей Celery
`rt_bus.process_inbox` в одной транзакции со статусом записи inbox. Исключение — автоповтор шины (30 с, 2 мин, 10 мин), затем
`failed` с возможностью «повторить» (`manage.py bus_retry --inbox <id>`). Логика — `services/crm_projections.py` (CRM) и
`services/eds_inbound.py` (EDS, волна 12: резолюция → задание расчёта, отказ → LOST, решение по КП — EDS-03), итог
доставки письма почтовым сервисом CRM — `notifications/mail_bus.py` (W18A-P1: журнал писем ERP, итог письма с КП).
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from rt_bus import Event, subscribe

from .services import crm_projections, eds_inbound


@subscribe("uz.railtech.crm.client.updated.v1")
def on_client_updated(event: Event) -> None:
    crm_projections.apply_client_snapshot(event.data)


@subscribe("uz.railtech.crm.contact.created.v1")
def on_contact_created(event: Event) -> None:
    crm_projections.apply_contact_snapshot(event.data, "contact.created")


@subscribe("uz.railtech.crm.contact.updated.v1")
def on_contact_updated(event: Event) -> None:
    crm_projections.apply_contact_snapshot(event.data, "contact.updated")


@subscribe("uz.railtech.crm.contact.deleted.v1")
def on_contact_deleted(event: Event) -> None:
    crm_projections.apply_contact_deleted(event.data)


@subscribe("uz.railtech.crm.mail.sent.v1")
def on_mail_sent(event: Event) -> None:
    from notifications.mail_bus import apply_mail_result

    apply_mail_result(event.type, event.data)


@subscribe("uz.railtech.crm.mail.failed.v1")
def on_mail_failed(event: Event) -> None:
    from notifications.mail_bus import apply_mail_result

    apply_mail_result(event.type, event.data)


@subscribe("uz.railtech.eds.letter.resolved.v1")
def on_letter_resolved(event: Event) -> None:
    eds_inbound.apply_letter_resolved(event.data, event_id=_event_uuid(event))


@subscribe("uz.railtech.eds.letter.rejected.v1")
def on_letter_rejected(event: Event) -> None:
    eds_inbound.apply_letter_rejected(event.data)


@subscribe("uz.railtech.eds.approval.decided.v1")
def on_approval_decided(event: Event) -> None:
    eds_inbound.apply_approval_decided(event.data)


def _event_uuid(event: Event) -> Optional[UUID]:
    try:
        return UUID(str(event.id))
    except ValueError:
        return None

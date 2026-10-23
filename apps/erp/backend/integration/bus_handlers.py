"""Обработчики входящих событий шины rt_bus в ERP (B3, L13): проекции данных клиента CRM.

Регистрируются в реестре по умолчанию при загрузке приложения (`IntegrationConfig.ready`); вызываются задачей Celery
`rt_bus.process_inbox` в одной транзакции со статусом записи inbox. Исключение — автоповтор шины (30 с, 2 мин, 10 мин), затем
`failed` с возможностью «повторить» (`manage.py bus_retry --inbox <id>`). Логика — `services/crm_projections.py`.
"""

from __future__ import annotations

from rt_bus import Event, subscribe

from .services import crm_projections


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

"""Адаптер SQLAlchemy 2 (async): таблицы на MetaData сервиса и `AsyncBus` (CRM, EDS, сервисы на FastAPI)."""

from .bus import AsyncBus
from .tables import BusTables, bus_tables

__all__ = ["AsyncBus", "BusTables", "bus_tables"]

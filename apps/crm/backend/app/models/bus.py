"""Таблицы шины rt_bus (ADR-0014, CONTRACTS §9): outbox, доставки, inbox, состояние подписчиков.

Схему объявляет библиотека (`rt_bus.sqlalchemy.bus_tables`), она совпадает с моделью Django в ERP
(L9). Здесь таблицы только попадают в `Base.metadata`, чтобы Alembic CRM видел их.
"""

from rt_bus.sqlalchemy import bus_tables

from app.models.base import Base

TABLES = bus_tables(Base.metadata)

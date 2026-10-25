"""Модели сервиса. Новая модель импортируется здесь — иначе Alembic её не увидит."""

from app.models.base import Base
from app.models.employee import Employee, SsoJti

__all__ = ["Base", "Employee", "SsoJti"]

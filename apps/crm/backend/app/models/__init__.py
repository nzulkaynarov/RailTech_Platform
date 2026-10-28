"""SQLAlchemy-модели (SPEC §5). Импорт модулей регистрирует таблицы в `Base.metadata`."""

from app.models import (  # noqa: F401
    auth,
    bus,
    clients,
    company_articles,
    deals,
    email,
    external_services,
    integrations,
    kb,
    leads,
    notices,
    platform_roles,
    qualification,
    reply_templates,
    staff_tickets,
    system,
)
from app.models.base import Base

__all__ = ["Base"]

"""SQLAlchemy-модели (SPEC §5). Импорт модулей регистрирует таблицы в `Base.metadata`."""

from app.models import (  # noqa: F401
    auth,
    clients,
    deals,
    email,
    external_services,
    integrations,
    kb,
    leads,
    platform_roles,
    qualification,
    reply_templates,
    system,
)
from app.models.base import Base

__all__ = ["Base"]

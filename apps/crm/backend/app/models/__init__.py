"""SQLAlchemy-модели (SPEC §5). Импорт модулей регистрирует таблицы в `Base.metadata`."""

from app.models import (  # noqa: F401
    auth,
    clients,
    deals,
    email,
    integrations,
    kb,
    leads,
    qualification,
    reply_templates,
    system,
)
from app.models.base import Base

__all__ = ["Base"]

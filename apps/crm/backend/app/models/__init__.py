"""SQLAlchemy-модели (SPEC §5). Импорт модулей регистрирует таблицы в `Base.metadata`."""

from app.models import (  # noqa: F401
    auth,
    clients,
    integrations,
    kb,
    leads,
    qualification,
    system,
)
from app.models.base import Base

__all__ = ["Base"]

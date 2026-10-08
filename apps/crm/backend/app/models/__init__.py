"""SQLAlchemy-модели (SPEC §5). Импорт модулей регистрирует таблицы в `Base.metadata`."""

from app.models import auth, clients, kb, leads, qualification  # noqa: F401
from app.models.base import Base

__all__ = ["Base"]

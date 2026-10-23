"""Роли Платформы как данные (ADR-0012, R-1): `platform_roles` и связь с сотрудниками."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PlatformRole(TimestampMixin, Base):
    """Роль Платформы: матрица `access` (раздел -> full|read, скрытые не хранятся) и поля.

    `code` есть у системных ролей (`ADMIN`, `DIRECTOR`) и ролей из шаблонов (`tpl:MANAGER`, ...);
    у созданных администратором пусто. Системные роли неизменны и не удаляются.
    """

    __tablename__ = "platform_roles"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(access) = 'object'", name="access"),
        CheckConstraint("jsonb_typeof(restricted_fields) = 'array'", name="restricted_fields"),
        Index("uq_platform_roles_lower_name", sql("lower(name)"), unique=True),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    code: Mapped[str | None] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, server_default=sql("''"))
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    # Оптимистическая блокировка (R-1b): растёт при изменении роли; PATCH присылает прочитанную.
    version: Mapped[int] = mapped_column(Integer, server_default=sql("1"))
    access: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=sql("'{}'::jsonb"))
    restricted_fields: Mapped[list[str]] = mapped_column(JSONB, server_default=sql("'[]'::jsonb"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class UserPlatformRole(Base):
    """Роль сотрудника (многие ко многим). Роль с сотрудниками удалить нельзя (RESTRICT)."""

    __tablename__ = "user_platform_roles"
    __table_args__ = (Index("ix_user_platform_roles_role_id", "role_id"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("platform_roles.id", ondelete="RESTRICT"), primary_key=True
    )
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def role_snapshot(role: PlatformRole) -> dict[str, Any]:
    """Содержимое роли для аудита «до/после»."""
    return {
        "name": role.name,
        "description": role.description,
        "access": dict(role.access),
        "restricted_fields": list(role.restricted_fields),
    }

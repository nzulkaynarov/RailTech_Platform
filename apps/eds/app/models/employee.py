"""Проекция сотрудников из событий `uz.railtech.identity.user.*.v1` (источник истины — CRM, ADR-0015)."""

import uuid
from datetime import datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Employee(Base):
    """Сотрудник и его права EDS. Пишет только обработчик шины; из API строки не создаются и не меняются.

    `updated_at` — версия снимка CRM (`user.updated_at`, у `user.deactivated` — время события): более
    старый снимок не применяется (L11). Строка с пустыми `email`/`full_name` — «надгробие»: `deactivated`
    пришёл раньше `created`; она не даёт запоздавшему старому снимку вернуть доступ.
    """

    __tablename__ = "employees"
    __table_args__ = (CheckConstraint("language IN ('ru', 'uz', 'en')", name="language"),)

    crm_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    email: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    position: Mapped[str | None] = mapped_column(String(120))
    language: Mapped[str] = mapped_column(String(2), server_default="ru")
    is_active: Mapped[bool] = mapped_column(Boolean)
    permissions_eds: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    # Разделы каталога (`erp.calc.goods` -> `full`) из `user.permissions.sections` (D1-8): зона исполнителя.
    sections: Mapped[dict[str, str]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class SsoJti(Base):
    """Использованные `jti` SSO-токенов: одноразовость обмена; хранятся 10 минут, уборка — задачей."""

    __tablename__ = "sso_jti"

    jti: Mapped[str] = mapped_column(String(128), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

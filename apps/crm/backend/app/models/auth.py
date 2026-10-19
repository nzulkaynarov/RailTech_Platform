"""Пользователи, роли, refresh-токены, аудит, политики Casbin (SPEC §5.1, ADR-0005)."""

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
    SmallInteger,
    String,
    Text,
    func,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

ROLES = ("admin", "manager", "viewer")
# Системы, куда сотруднику можно (FIX-11): CRM есть у всех, ERP выдаёт админ (`platform_access`).
PLATFORM_SYSTEMS = ("crm", "erp")


class User(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("ui_mode IN ('admin', 'manager')", name="ui_mode"),
        # JSON-список систем: всегда с "crm", других значений кроме "erp" нет (FIX-11).
        CheckConstraint(
            "jsonb_typeof(platform_access) = 'array' "
            "AND platform_access @> CAST('[\"crm\"]' AS jsonb) "
            'AND platform_access <@ CAST(\'["crm", "erp"]\' AS jsonb)',
            name="platform_access",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255))
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    must_change_password: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    ui_mode: Mapped[str] = mapped_column(String(8), server_default=sql("'manager'"))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_logins: Mapped[int] = mapped_column(Integer, server_default=sql("0"))
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Личные уведомления от бота (Q-010): системные алерты (админы) и сообщения своих лидов.
    notify_system: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    notify_leads: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    # Telegram отказал в личном сообщении (не нажат «Старт»/бот заблокирован); снимается успехом.
    tg_dm_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Куда пользователю можно (FIX-11, ADR-0003): `["crm"]` по умолчанию, `["crm", "erp"]` — доступ
    # к ERP выдан. Выдача → провижининг в ERP, снятие → отзыв сессий (`services/erp_access.py`).
    platform_access: Mapped[list[str]] = mapped_column(
        JSONB, server_default=sql("""'["crm"]'::jsonb""")
    )
    # Последняя ошибка синхронизации с ERP (провижининг или отзыв); NULL — ERP в курсе. Читает
    # проверка «Синхронизация с ERP» центра внешних сервисов (ADR-0024); пользователю не видна.
    erp_sync_error: Mapped[str | None] = mapped_column(Text)


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(SmallInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True)


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[int] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    granted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    family: Mapped[str] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str | None] = mapped_column(String(255))
    ip: Mapped[str | None] = mapped_column(INET)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'system', 'bot')", name="actor_type"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    actor_type: Mapped[str] = mapped_column(String(8))
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(INET)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CasbinRule(Base):
    """Таблица адаптера `casbin-async-sqlalchemy-adapter` (те же колонки)."""

    __tablename__ = "casbin_rule"

    id: Mapped[int] = mapped_column(Integer, Identity(), primary_key=True)
    ptype: Mapped[str | None] = mapped_column(String(255))
    v0: Mapped[str | None] = mapped_column(String(255))
    v1: Mapped[str | None] = mapped_column(String(255))
    v2: Mapped[str | None] = mapped_column(String(255))
    v3: Mapped[str | None] = mapped_column(String(255))
    v4: Mapped[str | None] = mapped_column(String(255))
    v5: Mapped[str | None] = mapped_column(String(255))


class SsoReplayToken(Base):
    """Использованные одноразовые jti SSO-токенов (M3-CRM-06, CONTRACTS §6)."""

    __tablename__ = "sso_replay_tokens"
    __table_args__ = (Index("ix_sso_replay_tokens_created_at", "created_at"),)

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

"""Пользователи, роли, refresh-токены, аудит, политики Casbin (SPEC §5.1, ADR-0005)."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
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
        # Роли ERP (FIX-63): JSON-массив кодов из каталога `domain/erp_roles.py`.
        CheckConstraint(
            "jsonb_typeof(erp_role_codes) = 'array' "
            'AND erp_role_codes <@ CAST(\'["CALCULATION", "CATALOG_SUPPLY", "FULFILLMENT", '
            '"FINANCE", "HEAD", "VIEWER"]\' AS jsonb)',
            name="erp_role_codes",
        ),
        # Язык интерфейса сотрудника (CRM-01b, Q-PLT-10-1 п. 6).
        CheckConstraint("language IN ('ru', 'uz', 'en')", name="language"),
        # Замещение (W15-H6): обе даты вместе, период не пуст, не сам себе. Заместитель может стать
        # NULL при заполненных датах (FK ON DELETE SET NULL): это «замещения нет».
        CheckConstraint(
            "(deputy_user_id IS NULL AND deputy_from IS NULL AND deputy_to IS NULL) OR "
            "(deputy_from IS NOT NULL AND deputy_to IS NOT NULL AND deputy_from <= deputy_to "
            "AND (deputy_user_id IS NULL OR deputy_user_id <> id))",
            name="deputy_period",
        ),
        Index("ix_users_deputy_user_id", "deputy_user_id"),
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
    # Системные роли бэк-офиса ERP, выданные админом CRM (FIX-63, Q-FIX50-1 (1)): уходят
    # в провижининг как `role_codes`; пусто по умолчанию. Хранятся и без доступа к ERP — уйдут
    # при его выдаче.
    erp_role_codes: Mapped[list[str]] = mapped_column(JSONB, server_default=sql("'[]'::jsonb"))
    # Роли Платформы — таблицы `platform_roles` и `user_platform_roles` (R-1, ADR-0012): непустой
    # набор вычисляет `user_roles`, `platform_access` и права ERP (`domain/platform_roles.py`).
    # Должность текстом (SPEC-v3 §4.3), ≤ 120 символов.
    position: Mapped[str | None] = mapped_column(String(120))
    # Язык интерфейса сотрудника ru|uz|en (CRM-01b); меняет сам себе или админ.
    language: Mapped[str] = mapped_column(String(2), server_default=sql("'ru'"))
    # Последняя ошибка синхронизации с ERP (провижининг или отзыв); NULL — ERP в курсе. Читает
    # проверка «Синхронизация с ERP» центра внешних сервисов (ADR-0024); пользователю не видна.
    erp_sync_error: Mapped[str | None] = mapped_column(Text)
    # Профиль, который правит сам сотрудник (W15-H6, ADR-0015: владелец полей — CRM).
    phone: Mapped[str | None] = mapped_column(String(32))
    timezone: Mapped[str] = mapped_column(String(64), server_default=sql("'Asia/Tashkent'"))
    email_signature: Mapped[str | None] = mapped_column(Text)
    # Ник Telegram, с которого сотрудник привязал бота («Привязан как @…»); у привязки админом NULL.
    tg_username: Mapped[str | None] = mapped_column(String(64))
    # Когда сотрудник привязал Telegram сам; NULL — привязал администратор или Telegram не привязан.
    tg_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Фото: ключ объекта в бакете файлов CRM (`domain/staff_profile.avatar_key`) и время замены
    # (версия адреса картинки). Файл отдаёт только API, публичных ссылок на S3 нет.
    avatar_key: Mapped[str | None] = mapped_column(String(255))
    avatar_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Замещение: на период включительно очередь сотрудника видит заместитель.
    deputy_user_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    deputy_from: Mapped[date | None] = mapped_column(Date)
    deputy_to: Mapped[date | None] = mapped_column(Date)
    # Когда пароль сброшен (ссылкой, админом, приглашением): выпущенные раньше access-токены не
    # принимаются: сессии сотрудника, в том числе живые в BFF, закрываются сразу, не через 15 минут.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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


class StaffTelegramLink(Base):
    """Одноразовый код привязки Telegram сотрудником (W15-H6): в БД только хеш, срок 10 минут."""

    __tablename__ = "staff_telegram_links"
    __table_args__ = (Index("ix_staff_telegram_links_user_id", "user_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordResetToken(Base):
    """Токен сброса пароля по ссылке (W15-H6): одноразовый, хеш, срок 60 минут."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        CheckConstraint("channel IN ('email', 'telegram')", name="channel"),
        Index("ix_password_reset_tokens_user_id", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    channel: Mapped[str] = mapped_column(String(8))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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

    def __str__(self) -> str:
        """Строка политики `p, sub, dom, obj, act` — по ней адаптер casbin загружает правила из БД
        (`load_policy`); без неё правила не читались и жили только в памяти процесса."""
        values = [self.ptype, self.v0, self.v1, self.v2, self.v3, self.v4, self.v5]
        parts: list[str] = []
        for value in values:
            if value is None:
                break
            parts.append(value)
        return ", ".join(parts)


class SsoReplayToken(Base):
    """Использованные одноразовые jti SSO-токенов (M3-CRM-06, CONTRACTS §6)."""

    __tablename__ = "sso_replay_tokens"
    __table_args__ = (Index("ix_sso_replay_tokens_created_at", "created_at"),)

    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

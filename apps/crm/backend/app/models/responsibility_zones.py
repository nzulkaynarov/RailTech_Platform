"""Реестр зон ответственности (ЕВ-З): зона — запись с ответственным, замещающим и куратором.

Образец — реестр прав подписи (EDS): человек, основание (номер и дата приказа), срок и журнал
(`audit_log`, действия `responsibility_zone.*`). Зона — данные: список заводит администратор из
существующих разделов каталога прав; в коде остаются только разделы и сигналы.
"""

from datetime import date
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    String,
    Text,
)
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

NAME_MAX_LEN = 120


class ResponsibilityZone(TimestampMixin, Base):
    __tablename__ = "responsibility_zones"
    __table_args__ = (
        CheckConstraint("jsonb_typeof(sections) = 'array'", name="sections"),
        CheckConstraint(
            "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to", name="term"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Стабильный слаг: на него ссылаются сигналы и (позже) маршруты; не меняется.
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name_ru: Mapped[str] = mapped_column(String(NAME_MAX_LEN))
    name_uz: Mapped[str] = mapped_column(String(NAME_MAX_LEN))
    name_en: Mapped[str] = mapped_column(String(NAME_MAX_LEN))
    description_ru: Mapped[str] = mapped_column(Text, server_default=sql("''"))
    description_uz: Mapped[str] = mapped_column(Text, server_default=sql("''"))
    description_en: Mapped[str] = mapped_column(Text, server_default=sql("''"))
    # Ключи разделов `platform-rbac.yaml`, к которым зона относится (проверяются по каталогу).
    sections: Mapped[list[str]] = mapped_column(JSONB, server_default=sql("'[]'::jsonb"))
    responsible_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    deputy_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    curator_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Основание назначения: номер и дата приказа.
    basis: Mapped[str] = mapped_column(Text, server_default=sql("''"))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


def zone_snapshot(zone: ResponsibilityZone) -> dict[str, Any]:
    """Содержимое зоны для журнала «до/после»."""
    return {
        "code": zone.code,
        "name": {"ru": zone.name_ru, "uz": zone.name_uz, "en": zone.name_en},
        "sections": list(zone.sections),
        "responsible_user_id": zone.responsible_user_id,
        "deputy_user_id": zone.deputy_user_id,
        "curator_user_id": zone.curator_user_id,
        "basis": zone.basis,
        "valid_from": zone.valid_from.isoformat() if zone.valid_from else None,
        "valid_to": zone.valid_to.isoformat() if zone.valid_to else None,
        "is_active": zone.is_active,
    }

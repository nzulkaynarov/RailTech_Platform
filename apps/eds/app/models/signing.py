"""Реестр полномочий подписи (ADR-0024 п. 1–2, 8): кто вправе подписывать какие виды документов, на какую сумму,
на каком основании и до какого срока; журнал выдачи, изменения и отзыва.

Владелец — EDS (ADR-0015). Замещение — не здесь: оно приходит проекцией из CRM (`employees.deputy_*`) и прав не даёт.
Инварианты основания держит и сервис (`services/signing_rules.py`, понятные ошибки), и база (CHECK) — запись в обход
сервиса их не нарушит.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

BASIS_CHARTER = "charter"
BASIS_ORDER = "order"
BASIS_POWER_OF_ATTORNEY = "power_of_attorney"
BASES = (BASIS_CHARTER, BASIS_ORDER, BASIS_POWER_OF_ATTORNEY)


class SigningAuthority(Base):
    """Полномочие одного сотрудника на подпись видов документов. Пересечения допустимы (устав и доверенность вместе).

    Отозванное полномочие остаётся в реестре (история, журнал); физически строка не удаляется.
    """

    __tablename__ = "signing_authorities"
    __table_args__ = (
        CheckConstraint("basis IN ('charter', 'order', 'power_of_attorney')", name="basis"),
        CheckConstraint("cardinality(kinds) > 0", name="kinds_not_empty"),
        CheckConstraint("(limit_amount IS NULL) = (limit_currency IS NULL)", name="limit_pair"),
        CheckConstraint("limit_amount IS NULL OR limit_amount > 0", name="limit_positive"),
        CheckConstraint("valid_to IS NULL OR valid_to >= valid_from", name="period"),
        # ГК РУз ст. 139: доверенность — номер, дата, срок обязательны; срок не больше трёх лет со дня выдачи.
        CheckConstraint(
            "basis <> 'power_of_attorney' OR (basis_number IS NOT NULL AND basis_date IS NOT NULL "
            "AND valid_to IS NOT NULL AND valid_to <= (basis_date + interval '3 years')::date)",
            name="power_of_attorney_terms",
        ),
        CheckConstraint(
            "basis <> 'order' OR (basis_number IS NOT NULL AND basis_date IS NOT NULL)", name="order_terms"
        ),
        CheckConstraint("basis <> 'charter' OR basis_number IS NULL", name="charter_without_number"),
        CheckConstraint("(revoked_at IS NULL) = (revoked_by IS NULL)", name="revoked_pair"),
        Index("ix_signing_authorities_user", "crm_user_id", "valid_from"),
        Index("ix_signing_authorities_kinds", "kinds", postgresql_using="gin"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    crm_user_id: Mapped[int] = mapped_column(BigInteger)
    kinds: Mapped[list[str]] = mapped_column(ARRAY(String(32)))
    limit_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    limit_currency: Mapped[str | None] = mapped_column(String(3))
    basis: Mapped[str] = mapped_column(String(24))
    basis_number: Mapped[str | None] = mapped_column(String(64))
    basis_date: Mapped[date | None] = mapped_column(Date)
    file_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("files.id", ondelete="SET NULL"))
    vakolat_url: Mapped[str | None] = mapped_column(String(500))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[int | None] = mapped_column(BigInteger)
    revoke_reason: Mapped[str | None] = mapped_column(Text)
    # Напоминание об окончании отправлено на эту дату окончания (повтор — только после переноса срока).
    expiry_notified_for: Mapped[date | None] = mapped_column(Date)


class SigningAuthorityEvent(Base):
    """Журнал полномочия: выдано, изменено, отозвано, основание заменено, напоминание об окончании.

    `details` — что именно изменилось (поле → было/стало); секретов и токенов нет.
    """

    __tablename__ = "signing_authority_events"
    __table_args__ = (Index("ix_signing_authority_events_authority", "authority_id", "id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    authority_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("signing_authorities.id", ondelete="CASCADE"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    action: Mapped[str] = mapped_column(String(32))
    by_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)
    comment: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))

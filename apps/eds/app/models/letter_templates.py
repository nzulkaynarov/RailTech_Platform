"""Шаблоны писем и служебок (план 2026-11-12 п. 3.6; исследование 2026-11-11 «Документы и шаблоны» §2–3, TPL-4).

Один шаблон — варианты по языкам: `variants = {ru?, uz?, en?}`, каждый — полное тело rt-docs со своим `lang`.
Встроенный шаблон (`builtin_key`) живёт и в коде (`services/letter_templates.BUILTINS`); «изменён» — вариант разошёлся с
исходником, «Вернуть по умолчанию» заменяет варианты исходником. По умолчанию — не больше одного шаблона на вид.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Index, String, Uuid
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TEMPLATE_KINDS = ("letter", "memo")


class LetterTemplate(Base):
    __tablename__ = "letter_templates"
    __table_args__ = (
        CheckConstraint("kind IN ('letter', 'memo')", name="kind"),
        Index("uq_letter_templates_default", "kind", unique=True, postgresql_where=sql("is_default")),
        Index(
            "uq_letter_templates_builtin", "builtin_key", unique=True, postgresql_where=sql("builtin_key IS NOT NULL")
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String(120))
    variants: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql("'{}'::jsonb"))
    is_default: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))
    builtin_key: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[int | None] = mapped_column(BigInteger)  # встроенный — NULL
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

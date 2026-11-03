"""Шаблоны резолюций пути делопроизводства (EDS-REG, R2; исследование 2026-11-02 «Маршруты» §4.2).

Шаблон — данные: название, вид резолюции (поведение — закрытый список кода `execute|reply|info`), текст, кто
ответственный (сотрудник, адресат письма или «выбрать при резолюции»), соисполнители, «ознакомить», срок в днях.
Личный — у владельца (`owner_crm_user_id`), общий (`company`) ведёт администратор. Применение только заполняет форму
резолюции, письмо шаблон не хранит: правка или удаление шаблона резолюции не меняют.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy import text as sql
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

TEMPLATE_SCOPES = ("personal", "company")
RESPONSIBLE_TYPES = ("person", "addressee", "none")


class ResolutionTemplate(Base):
    __tablename__ = "resolution_templates"
    __table_args__ = (
        CheckConstraint("scope IN ('personal', 'company')", name="scope"),
        CheckConstraint("kind IN ('execute', 'reply', 'info')", name="kind"),
        CheckConstraint("responsible_type IN ('person', 'addressee', 'none')", name="responsible_type"),
        CheckConstraint("(scope = 'personal') = (owner_crm_user_id IS NOT NULL)", name="owner_by_scope"),
        Index("ix_resolution_templates_owner", "owner_crm_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(120))
    scope: Mapped[str] = mapped_column(String(16))
    owner_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)  # личный — владелец; общий — NULL
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    responsible_type: Mapped[str] = mapped_column(String(16), server_default=sql("'none'"))
    responsible_crm_user_id: Mapped[int | None] = mapped_column(BigInteger)
    co_executor_ids: Mapped[list[Any]] = mapped_column(JSONB, server_default=sql("'[]'::jsonb"))
    acquaint_ids: Mapped[list[Any]] = mapped_column(JSONB, server_default=sql("'[]'::jsonb"))
    due_days: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

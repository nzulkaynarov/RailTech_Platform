"""Поручения по входящим письмам, переносы сроков и ознакомление (P8b, SPEC-v3 §3.2a п. 2–5; бенчмарк СЭД §6.2–6.3).

Резолюция пути делопроизводства «К исполнению» или «Подготовить ответ» создаёт поручение ответственному и каждому
соисполнителю: «В работе» → «Исполнено»; просрочка — признак (срок прошёл, не исполнено), не статус. Перенос срока —
отдельная строка запроса с решением автора резолюции; история переносов — строки по поручению. «Ознакомить» —
строка на сотрудника с датой «Ознакомлен».
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

INSTRUCTION_KINDS = ("execute", "reply")
INSTRUCTION_ROLES = ("responsible", "co_executor")
INSTRUCTION_STATUSES = ("in_work", "executed")
EXTENSION_STATUSES = ("pending", "approved", "rejected")


class Instruction(Base):
    """Поручение сотруднику по письму. `reminders_sent` — какие напоминания о текущем сроке уже ушли (`d3`, `d1`, `d0`,
    `overdue`); одобренный перенос их сбрасывает."""

    __tablename__ = "instructions"
    __table_args__ = (
        CheckConstraint("kind IN ('execute', 'reply')", name="kind"),
        CheckConstraint("role IN ('responsible', 'co_executor')", name="role"),
        CheckConstraint("status IN ('in_work', 'executed')", name="status"),
        UniqueConstraint("letter_id", "crm_user_id", name="uq_instructions_letter_person"),
        Index("ix_instructions_person_status", "crm_user_id", "status"),
        Index("ix_instructions_status_due", "status", "due"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    letter_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("letters.id", ondelete="CASCADE"), index=True)
    crm_user_id: Mapped[int] = mapped_column(BigInteger)
    role: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    due: Mapped[date] = mapped_column(Date)
    text: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    report: Mapped[str | None] = mapped_column(Text)
    outgoing_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL")
    )
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reminders_sent: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=sql_text("'{}'::text[]"))
    created_by: Mapped[int] = mapped_column(BigInteger)  # автор резолюции
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class InstructionExtension(Base):
    """Запрос переноса срока и решение автора резолюции. Без решения у поручения не больше одного запроса."""

    __tablename__ = "instruction_extensions"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'approved', 'rejected')", name="status"),
        Index(
            "uq_instruction_extensions_pending",
            "instruction_id",
            unique=True,
            postgresql_where=sql_text("status = 'pending'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    instruction_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("instructions.id", ondelete="CASCADE"), index=True
    )
    old_due: Mapped[date] = mapped_column(Date)
    new_due: Mapped[date] = mapped_column(Date)
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16))
    requested_by: Mapped[int] = mapped_column(BigInteger)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[int | None] = mapped_column(BigInteger)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    comment: Mapped[str | None] = mapped_column(Text)


class Acquaintance(Base):
    """«Ознакомить»: сотрудник и дата «Ознакомлен» (`None` — ждёт)."""

    __tablename__ = "letter_acquaintances"
    __table_args__ = (
        UniqueConstraint("letter_id", "crm_user_id", name="uq_letter_acquaintances_letter_person"),
        Index("ix_letter_acquaintances_person", "crm_user_id", "acknowledged_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    letter_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("letters.id", ondelete="CASCADE"))
    crm_user_id: Mapped[int] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

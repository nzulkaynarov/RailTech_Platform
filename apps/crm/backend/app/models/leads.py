"""Лиды, Telegram-идентичности, диалоги, сообщения, заметки (SPEC §5.2, §5.3)."""

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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

STAGES = (
    "'new','engaged','qualified','handoff','in_progress','won','customer','lost','unresponsive'"
)


class Lead(TimestampMixin, Base):
    __tablename__ = "leads"
    __table_args__ = (
        CheckConstraint(f"stage IN ({STAGES})", name="stage"),
        CheckConstraint("owner_mode IN ('bot', 'human', 'paused')", name="owner_mode"),
        CheckConstraint("language IN ('ru', 'uz', 'en')", name="language"),
        CheckConstraint("score BETWEEN 0 AND 100", name="score"),
        Index("ix_leads_stage", "stage"),
        Index("ix_leads_last_lead_msg_at", "last_lead_msg_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), server_default=sql("''"))
    language: Mapped[str] = mapped_column(String(2), server_default=sql("'ru'"))
    language_confirmed: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    language_candidate: Mapped[str | None] = mapped_column(String(2))
    stage: Mapped[str] = mapped_column(String(16), server_default=sql("'new'"))
    score: Mapped[int] = mapped_column(Integer, server_default=sql("0"))
    owner_mode: Mapped[str] = mapped_column(String(8), server_default=sql("'bot'"))
    assigned_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    consent_given_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_version: Mapped[str | None] = mapped_column(String(32))
    need_summary: Mapped[str | None] = mapped_column(Text)
    product_interest: Mapped[list[str]] = mapped_column(
        ARRAY(String(64)), server_default=sql("'{}'")
    )
    qualification: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql("'{}'::jsonb"))
    consecutive_fallbacks: Mapped[int] = mapped_column(Integer, server_default=sql("0"))
    bot_turns_without_progress: Mapped[int] = mapped_column(Integer, server_default=sql("0"))
    last_lead_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_bot_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_human_msg_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    unresponsive_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    handoff_notice_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    erased_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16), server_default=sql("'telegram'"))
    notes_count: Mapped[int] = mapped_column(Integer, server_default=sql("0"))

    identities: Mapped[list["TelegramIdentity"]] = relationship(back_populates="lead")


class TelegramIdentity(TimestampMixin, Base):
    __tablename__ = "telegram_identities"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tg_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    tg_username: Mapped[str | None] = mapped_column(String(64))
    tg_first_name: Mapped[str | None] = mapped_column(String(255))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("clients.id", ondelete="SET NULL"))
    phone_e164: Mapped[str | None] = mapped_column(String(20))
    verified_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_blocked: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))

    lead: Mapped[Lead | None] = relationship(back_populates="identities")


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (Index("ix_conversations_lead_id", "lead_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    channel: Mapped[str] = mapped_column(String(16), server_default=sql("'telegram'"))
    tg_chat_id: Mapped[int] = mapped_column(BigInteger)
    is_open: Mapped[bool] = mapped_column(Boolean, server_default=sql("true"))


class Message(TimestampMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('lead', 'bot', 'manager', 'system')", name="role"),
        Index("ix_messages_conversation_id_id", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(8))
    text: Mapped[str] = mapped_column(Text, server_default=sql("''"))
    attachments: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=sql("'[]'::jsonb")
    )
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger)
    sent_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=sql("'{}'::jsonb"))


class TgUpdate(Base):
    __tablename__ = "tg_updates"

    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class LeadNote(TimestampMixin, Base):
    __tablename__ = "lead_notes"
    __table_args__ = (Index("ix_lead_notes_lead_id", "lead_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    visible_to_bot: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB)
    schema_version: Mapped[int] = mapped_column(Integer, server_default=sql("1"))
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

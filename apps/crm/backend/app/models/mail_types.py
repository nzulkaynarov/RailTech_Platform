"""Типы входящих писем и правила отправителя (MAIL-TYPES; домен — `domain/mail_types.py`).

`mail_types` — справочник администратора: код (латиница, не меняется — письмо хранит его строкой),
название
ru/uz/en, цвет и значок из закрытого набора, действие по умолчанию из закрытого списка кода,
«действует», порядок.
`mail_sender_rules` — «отправитель или домен → тип» (как фильтры Gmail и правила Front):
применяется до помощника
и побеждает его; удалить тип с правилом нельзя, пока правило есть.
"""

from datetime import datetime

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
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class MailType(TimestampMixin, Base):
    __tablename__ = "mail_types"
    __table_args__ = (
        CheckConstraint(
            "default_action IN ('register_incoming', 'create_lead', 'supplier_price', "
            "'to_accountant', 'archive_mailing', 'reply_template', 'suspicious')",
            name="default_action",
        ),
        CheckConstraint(
            "color IN ('blue', 'green', 'gold', 'red', 'purple', 'cyan', 'default')", name="color"
        ),
        CheckConstraint(
            "icon IN ('mail', 'team', 'calendar', 'file', 'wallet', 'bank', 'notification', "
            "'stop')",
            name="icon",
        ),
        Index("ix_mail_types_position", "position"),
    )

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_ru: Mapped[str] = mapped_column(String(120), nullable=False)
    name_uz: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    name_en: Mapped[str] = mapped_column(String(120), nullable=False, server_default="")
    color: Mapped[str] = mapped_column(String(16), nullable=False, server_default="default")
    icon: Mapped[str] = mapped_column(String(16), nullable=False, server_default="mail")
    default_action: Mapped[str] = mapped_column(String(24), nullable=False)
    # Вид документа EDS (код `letter-kinds`) для предзаполнения формы ВХ из письма этого типа.
    letter_kind: Mapped[str | None] = mapped_column(String(32))
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    position: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")


class MailSenderRule(Base):
    __tablename__ = "mail_sender_rules"
    __table_args__ = (Index("uq_mail_sender_rules_pattern", "pattern", unique=True),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    pattern: Mapped[str] = mapped_column(
        String(255), nullable=False
    )  # адрес или домен, нижний регистр
    type_code: Mapped[str] = mapped_column(
        String(32), ForeignKey("mail_types.code", ondelete="RESTRICT"), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

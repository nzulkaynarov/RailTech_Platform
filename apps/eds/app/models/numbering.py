"""Счётчики номеров реестра: строка на (тип, год) под `SELECT … FOR UPDATE` (runbook волны 12 §2.1)."""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NumberCounter(Base):
    """Последний выданный номер типа за год. Строка живёт в транзакции создания документа: откат возвращает счётчик."""

    __tablename__ = "number_counters"

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class NumberLabel(Base):
    """Обозначение вида номера (задача «Н», решение владельца 2026-11-13): задаёт владелец в «Настройки · Нумерация».
    Строки нет — умолчание из кода (латиницей). Выданные номера не меняются."""

    __tablename__ = "number_labels"

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    label: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

"""Счётчики номеров реестра: строка на (тип, год) под `SELECT … FOR UPDATE` (runbook волны 12 §2.1)."""

from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class NumberCounter(Base):
    """Последний выданный номер типа за год. Строка живёт в транзакции создания документа: откат возвращает счётчик."""

    __tablename__ = "number_counters"

    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    last_value: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")

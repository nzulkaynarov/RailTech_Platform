"""Справочники документооборота как данные (EDS-REG; `docs/research/2026-11-02-flexibility/4-settings-ia.md` §4.3).

Одна таблица на все справочники EDS: строка — значение вида `kind` (`letter-kinds`, `receipt-methods`). Название,
порядок, «действует» и дополнительные поля (`attrs`) — данные администратора; что значат поля и какие виды бывают — код
(`services/dictionaries.py`, закрытый список). Письма хранят код значения строкой, без внешнего ключа: старые письма с
удалённым кодом не ломаются, а использованное значение удалить нельзя — только скрыть.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class DictionaryItem(Base):
    __tablename__ = "dictionary_items"

    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name_ru: Mapped[str] = mapped_column(String(120))
    name_uz: Mapped[str] = mapped_column(String(120), server_default=text("''"))
    name_en: Mapped[str] = mapped_column(String(120), server_default=text("''"))
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    position: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

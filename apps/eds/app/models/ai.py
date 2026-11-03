"""Журнал ИИ-помощника и настройки документооборота (EDS-REG «Заполнить из файла»).

* `ai_suggestions` — журнал вызовов по решению юриста 2026-11-02: кто, когда, функция, алиас, версия промпта,
  источник (текст или изображение), итог вызова, токены и стоимость, решение человека (принял · поправил · вручную).
  **Без текстов**: ни файла, ни ответа модели здесь нет.
* `docflow_settings` — одна строка настроек документооборота (администратор): `recognize_scans` — распознавать сканы и
  фото моделью, по умолчанию выключено.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, Integer, Numeric, SmallInteger, String, Uuid
from sqlalchemy import text as sql
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

AI_STATUSES = ("ok", "error", "refusal", "invalid", "budget", "empty")
AI_DECISIONS = ("accepted", "edited", "manual")


class AiSuggestion(Base):
    __tablename__ = "ai_suggestions"
    __table_args__ = (
        CheckConstraint("status IN ('ok', 'error', 'refusal', 'invalid', 'budget', 'empty')", name="status"),
        CheckConstraint("decision IS NULL OR decision IN ('accepted', 'edited', 'manual')", name="decision"),
        CheckConstraint("source IN ('text', 'image')", name="source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    function: Mapped[str] = mapped_column(String(32))
    alias: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16))
    error_code: Mapped[str | None] = mapped_column(String(32))
    crm_user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=sql("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=sql("0"))
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    decision: Mapped[str | None] = mapped_column(String(16))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocflowSettings(Base):
    __tablename__ = "docflow_settings"
    __table_args__ = (CheckConstraint("id = 1", name="single_row"),)

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    recognize_scans: Mapped[bool] = mapped_column(Boolean, server_default=sql("false"))
    updated_by: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

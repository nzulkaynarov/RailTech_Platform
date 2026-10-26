"""Ключи идемпотентности создающих POST (`Idempotency-Key`, 24 часа, eds.yaml)."""

from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class IdempotencyKey(Base):
    """Повтор с тем же ключом и телом возвращает прежний ответ; с другим телом — 409 `idempotency_key_reused`."""

    __tablename__ = "idempotency_keys"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    crm_user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    scope: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

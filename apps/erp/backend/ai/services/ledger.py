"""Запись вызова шлюза в журнал ``ai.AICall`` (бюджет дня, версия промпта, статус для админа)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from django.db import DatabaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CallUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal | None = None
    latency_ms: int = 0


@dataclass(frozen=True)
class CallRecord:
    session_id: str
    user_id: int | None
    feature: str
    alias: str
    prompt_name: str
    prompt_version: str
    status: str
    error_code: str
    usage: CallUsage


def record_call(record: CallRecord) -> None:
    """Одна строка журнала. Сбой записи не роняет вызов (журнал — учёт, не бизнес-данные)."""
    from ai.models import AICall

    try:
        AICall.objects.create(
            session_id=record.session_id[:64],
            user_id=record.user_id,
            feature=record.feature[:32],
            model_alias=record.alias[:32],
            prompt_name=record.prompt_name[:64],
            prompt_version=record.prompt_version[:16],
            status=record.status[:16],
            error_code=(record.error_code or "")[:40],
            input_tokens=max(record.usage.input_tokens, 0),
            output_tokens=max(record.usage.output_tokens, 0),
            cost_usd=record.usage.cost_usd or Decimal("0"),
            latency_ms=max(record.usage.latency_ms, 0),
        )
    except DatabaseError:
        logger.exception("AI call ledger write failed (feature=%s)", record.feature)

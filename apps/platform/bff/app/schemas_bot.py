"""Модели Admin · Настройки бота (контракт platform-bff.yaml 0.11.0, тег `bot`).

Значения и схемы разделов настроек приходят из CRM как есть (JSON Schema Pydantic CRM): форма
строится по схеме, поэтому BFF не знает перечня полей и не отстаёт от CRM. Правила передачи
(`EscalationSettingsIn`) и шаблоны ответов повторяют ограничения CRM, чтобы отказ приходил до
сети; решает CRM.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class BotSettings(BaseModel):
    values: dict[str, dict[str, Any]]
    schemas: dict[str, dict[str, Any]]


class EscalationSettingsIn(BaseModel):
    """Правила передачи менеджеру; в CRM уходят только указанные поля."""

    model_config = ConfigDict(extra="forbid")

    high_score_threshold: int | None = Field(default=None, ge=0, le=100)
    no_progress_turns: int | None = Field(default=None, ge=1)
    kb_gap_streak: int | None = Field(default=None, ge=1)
    qualifier_min_confidence: float | None = Field(default=None, ge=0, le=1)
    sla_minutes: int | None = Field(default=None, ge=1)
    reminder_minutes: int | None = Field(default=None, ge=1)
    disabled_triggers: list[str] | None = None
    price_always_to_manager: bool | None = None
    require_phone_for_human_request: bool | None = None
    human_request_terms: list[str] | None = None


class EscalationDryRunRow(BaseModel):
    run_id: int
    lead_id: int
    at: datetime
    current: list[str]
    candidate: list[str]


class EscalationDryRun(BaseModel):
    dialogs: int
    escalated_current: int
    escalated_candidate: int
    by_code_current: dict[str, int]
    by_code_candidate: dict[str, int]
    changed: list[EscalationDryRunRow]


class LocalizedText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ru: str
    uz: str
    en: str


class ReplyTemplate(BaseModel):
    id: int
    title: str
    text: LocalizedText
    updated_at: datetime


class ReplyTemplateList(BaseModel):
    items: list[ReplyTemplate]


class ReplyTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    text: LocalizedText

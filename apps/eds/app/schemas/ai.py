"""Схемы ИИ-помощника регистрации и настроек (eds.yaml: LetterIntake*, AiDecisionIn, DocflowSettings)."""

import datetime as dt
import uuid
from enum import StrEnum

from pydantic import BaseModel

from app.schemas.common import Strict


class LetterIntakeIn(Strict):
    file_id: uuid.UUID


class IntakeSource(StrEnum):
    TEXT = "text"  # текстовый слой PDF, маскированный
    IMAGE = "image"  # скан или фото — модель с изображением


class LetterIntakeFields(BaseModel):
    sender_name: str | None = None
    sender_inn: str | None = None
    sender_ref_number: str | None = None
    sender_ref_date: dt.date | None = None
    subject: str | None = None
    summary: str | None = None
    kind: str | None = None
    document_due: dt.date | None = None


class LetterIntakeSuggestion(BaseModel):
    suggestion_id: uuid.UUID
    source: IntakeSource
    fields: LetterIntakeFields
    alias: str
    prompt_version: str


class AiDecision(StrEnum):
    ACCEPTED = "accepted"
    EDITED = "edited"
    MANUAL = "manual"


class AiDecisionIn(Strict):
    decision: AiDecision


class PiiPolicy(StrEnum):
    BUSINESS = "business"  # «Деловая»: скрываются паспорт, ПИНФЛ, номера карт, даты рождения
    STRICT = "strict"  # «Строгая»: скрывается всё прежнее, сканы и фото в модель не уходят


class DocflowSettings(BaseModel):
    recognize_scans: bool
    # Политика защиты данных для ИИ — проекция настройки CRM (владелец поля — CRM), здесь только для чтения.
    pii_policy: PiiPolicy
    ai_available: bool


class DocflowSettingsPatch(Strict):
    recognize_scans: bool

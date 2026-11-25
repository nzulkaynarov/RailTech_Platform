"""Схемы ИИ-помощника регистрации и настроек (eds.yaml: LetterIntake*, AiDecisionIn, DocflowSettings)."""

import datetime as dt
import uuid
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import Strict


class LetterIntakeIn(Strict):
    file_id: uuid.UUID
    received_at: dt.date | None = None  # дата поступления: от неё код считает срок «в течение N дней»
    rules_only: bool = False  # только правила кода, без модели («Пересчитать срок»): платного вызова нет


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
    # поля, которые посчитал код, а не модель (срок по обороту «в течение N дней», ИНН): экран метит их отдельно
    by_code: list[str] = Field(default_factory=list)


class LetterAssistIn(Strict):
    """План 1.4: «Подготовить текст» (`draft`: о чём письмо) или «Перевести» (`translate`: тело на язык `lang`)."""

    action: Literal["draft", "translate"]
    lang: Literal["ru", "uz", "en"]
    brief: Annotated[str | None, Field(max_length=4000)] = None
    recipient: Annotated[str | None, Field(max_length=300)] = None
    subject: Annotated[str | None, Field(max_length=300)] = None
    body: dict[str, Any] | None = None


class LetterAssistSuggestion(BaseModel):
    """Предложение помощника: тело письма по контракту документов; у перевода — обратный перевод на русский."""

    suggestion_id: uuid.UUID
    body: dict[str, Any]
    back_translation: str | None
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
    #: ГЛ-0: автор письма с правом подписи подписывает его сам (по умолчанию да); нет — «автор ≠ подписант»
    author_may_sign_own_letter: bool = True


class DocflowSettingsPatch(Strict):
    recognize_scans: bool | None = None
    author_may_sign_own_letter: bool | None = None

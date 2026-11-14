"""«Заполнить из файла» и настройки документооборота (контракт BFF, EDS-REG)."""

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas_eds_documents import EdsDocumentBody


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LetterIntakeIn(_In):
    file_id: uuid.UUID


class LetterIntakeFields(BaseModel):
    sender_name: str | None = None
    sender_inn: Annotated[str, StringConstraints(pattern=r"^\d{9,14}$")] | None = None
    sender_ref_number: str | None = None
    sender_ref_date: dt.date | None = None
    subject: str | None = None
    summary: str | None = None
    kind: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z_]{0,31}$")] | None = None
    document_due: dt.date | None = None


class LetterIntakeSuggestion(BaseModel):
    suggestion_id: uuid.UUID
    source: Literal["text", "image"]
    fields: LetterIntakeFields
    alias: str
    prompt_version: str


class AiDecisionIn(_In):
    decision: Literal["accepted", "edited", "manual"]


class DocflowSettings(BaseModel):
    recognize_scans: bool
    # Политика защиты данных для ИИ — проекция настройки CRM (`ai.pii_policy`), только чтение
    pii_policy: Literal["business", "strict"]
    ai_available: bool


class DocflowSettingsPatch(_In):
    recognize_scans: bool


class LetterAssistIn(BaseModel):
    """План 1.4: «Подготовить текст» (`draft`) или «Перевести» (`translate`); правила — в EDS."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["draft", "translate"]
    lang: Literal["ru", "uz", "en"]
    brief: str | None = Field(default=None, max_length=4000)
    recipient: str | None = Field(default=None, max_length=300)
    subject: str | None = Field(default=None, max_length=300)
    body: EdsDocumentBody | None = None


class LetterAssistSuggestion(BaseModel):
    suggestion_id: uuid.UUID
    body: EdsDocumentBody
    back_translation: str | None

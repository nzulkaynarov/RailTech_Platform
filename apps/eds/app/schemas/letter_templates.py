"""Шаблоны писем и служебок (TPL-4, eds.yaml `/templates`)."""

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import Strict
from app.schemas.documents import DocumentBody

TemplateKind = Literal["letter", "memo"]
TemplateLang = Literal["ru", "uz", "en"]


class TemplateVariants(Strict):
    """Варианты по языкам; `lang` тела совпадает с ключом (проверяет сервис)."""

    ru: DocumentBody | None = None
    uz: DocumentBody | None = None
    en: DocumentBody | None = None


class LetterTemplateIn(Strict):
    kind: TemplateKind
    name: Annotated[str, Field(min_length=1, max_length=120)]
    variants: TemplateVariants
    is_default: bool = False
    active: bool = True


class LetterTemplateOut(BaseModel):
    id: uuid.UUID
    kind: TemplateKind
    name: str
    variants: dict[TemplateLang, dict[str, Any]]  # тела как хранятся: нормализованы rt-docs, без пустых полей
    languages: list[TemplateLang]
    is_default: bool
    active: bool
    origin: Literal["builtin", "custom"]
    changed: bool  # встроенный и разошёлся с исходником
    updated_at: dt.datetime


class LetterTemplateList(BaseModel):
    items: list[LetterTemplateOut]


class TemplatePreviewIn(Strict):
    """Предпросмотр варианта на бланке: тело как в редакторе, не сохраняется."""

    body: DocumentBody
    kind: TemplateKind = "letter"


class TemplatePreview(BaseModel):
    """PDF предпросмотра из общей очереди рендера: по `hash` — состояние и файл."""

    hash: str
    status: Literal["pending", "ready", "failed"]
    error: str | None
    pages: int | None

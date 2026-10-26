"""Модели CRM · База знаний (контракт platform-bff.yaml 0.11.0, тег `kb`).

Ответы BFF — подмножество ответов CRM (`crm_models`): документы, фрагменты, поиск, пробелы,
продукты и песочница. Перечни (`ingest_status`, `source_type`, статус пробела) закрыты проверками
базы CRM, поэтому здесь они `Literal`. Тела запросов повторяют ограничения CRM, чтобы отказ
приходил из BFF до сети, но решает CRM.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Language = Literal["ru", "uz", "en"]
IngestStatus = Literal["pending", "processing", "done", "failed"]
SourceType = Literal["file", "url", "manual"]
GapStatus = Literal["open", "resolved", "ignored"]


class CreatedId(BaseModel):
    id: int


class KbDocument(BaseModel):
    id: int
    title: str
    product_key: str | None
    language: Language
    source_type: SourceType
    mime: str | None
    version: int
    is_active: bool
    ingest_status: IngestStatus
    ingest_error: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KbDocumentList(BaseModel):
    items: list[KbDocument]


class KbManualDocumentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=500)
    markdown: str = Field(min_length=1, max_length=200_000)
    language: Language
    product_key: str | None = None
    gap_id: int | None = None


class KbDocumentPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=500)
    is_active: bool | None = None
    product_key: str | None = None
    clear_product: bool | None = None


class KbChunk(BaseModel):
    id: int
    position: int
    heading_path: str | None
    content: str
    token_count: int


class KbChunkList(BaseModel):
    items: list[KbChunk]


class KbSearchIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    language: Language | None = None
    product_key: str | None = None
    top_k: int = Field(default=6, ge=1, le=10)


class KbSearchHit(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    heading_path: str | None
    content: str
    similarity: float | None
    rrf_score: float


class KbSearchResult(BaseModel):
    hits: list[KbSearchHit]
    best_score: float | None
    min_score: float
    confident: bool
    language: Language


class KbGap(BaseModel):
    id: int
    lead_id: int | None
    question: str
    language: Language
    best_score: float | None
    occurrences: int
    status: GapStatus
    resolved_document_id: int | None
    created_at: datetime
    updated_at: datetime


class KbGapPage(BaseModel):
    items: list[KbGap]
    total: int


class KbGapResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: int = Field(ge=1)


class KbProduct(BaseModel):
    key: str
    name: str
    description: str | None
    is_active: bool


class KbProductList(BaseModel):
    items: list[KbProduct]


class SandboxMessageIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=4000)
    language: Language = "ru"


class SandboxReply(BaseModel):
    text: str
    buttons: list[str]


class SandboxWhy(BaseModel):
    decision: str
    reason: str | None
    best_score: float | None
    documents: list[str]
    triggers: list[str]
    priority: str | None


class SandboxTurn(BaseModel):
    replies: list[SandboxReply]
    why: SandboxWhy

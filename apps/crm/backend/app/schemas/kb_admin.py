"""DTO администрирования базы знаний (PLAN Фаза 5)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Language = Literal["ru", "uz", "en"]


class KbDocumentOut(BaseModel):
    id: int
    title: str
    product_key: str | None
    language: str
    source_type: str
    mime: str | None
    version: int
    is_active: bool
    ingest_status: str
    ingest_error: str | None
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KbDocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=500)
    is_active: bool | None = None
    product_key: str | None = None
    clear_product: bool = False


class ManualDocument(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    markdown: str = Field(min_length=1, max_length=200_000)
    language: Language
    product_key: str | None = None
    gap_id: int | None = None


class KbChunkOut(BaseModel):
    id: int
    position: int
    heading_path: str | None
    content: str
    token_count: int


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    language: Language | None = None
    product_key: str | None = None
    top_k: int = Field(default=6, ge=1, le=10)


class SearchHitOut(BaseModel):
    chunk_id: int
    document_id: int
    document_title: str
    heading_path: str | None
    content: str
    similarity: float | None
    rrf_score: float


class SearchResponse(BaseModel):
    hits: list[SearchHitOut]
    best_score: float | None
    min_score: float
    confident: bool
    language: str


class KbGapOut(BaseModel):
    id: int
    lead_id: int | None
    question: str
    language: str
    best_score: float | None
    occurrences: int
    status: str
    resolved_document_id: int | None
    created_at: datetime
    updated_at: datetime


class KbGapPage(BaseModel):
    items: list[KbGapOut]
    total: int


class ResolveGap(BaseModel):
    document_id: int


class ProductOut(BaseModel):
    key: str
    name: str
    description: str | None
    is_active: bool


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    is_active: bool = True


class Created(BaseModel):
    id: int

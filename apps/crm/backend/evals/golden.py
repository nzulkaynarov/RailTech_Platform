"""Схема golden-кейсов (`evals/golden/*.yaml`) и загрузчик. Категории — SPEC §12."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

GOLDEN_DIR = Path(__file__).parent / "golden"

Category = Literal[
    "kb_answer",
    "not_in_kb",
    "human_request",
    "negative",
    "competitor",
    "smalltalk",
    "injection",
    "no_progress",
    "unresponsive_return",
    "customer_document",
    "service_mode",
]
Language = Literal["ru", "uz", "en"]
ActionName = Literal["answer", "fallback", "handoff", "silent", "deliver_document"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Turn(_Strict):
    role: Literal["lead", "bot", "manager"]
    text: str


class Expect(_Strict):
    actions: list[ActionName] = Field(min_length=1, description="допустимые решения узла decide")
    reply_language: Language | None = None
    kb_document: str | None = Field(default=None, description="заголовок документа в контексте")
    must_include_any: list[str] = Field(default_factory=list)
    must_not_include: list[str] = Field(default_factory=list)
    max_words: int = 120
    tool_calls_any: list[str] = Field(default_factory=list, description="хотя бы один вызов")
    erp_tools_any: list[str] = Field(
        default_factory=list, description="сервисный режим: хотя бы один вызов инструмента erp-mcp"
    )
    no_erp_calls: bool = Field(default=False, description="ни одного вызова erp-mcp (лид, чужое)")


class EvalDocument(_Strict):
    document_id: int
    title: str
    type: Literal["contract", "proposal", "letter", "invoice", "act", "other"]
    number: str | None = None
    doc_date: str | None = None


class ErpFixture(_Strict):
    """erp-mcp в кейсе сервисного режима: ответы инструментов (форма — `mcp-tools.json`)."""

    available: bool = Field(default=True, description="False — erp-mcp не отвечает")
    tools: dict[str, Any] = Field(default_factory=dict, description="имя инструмента → результат")


class GoldenCase(_Strict):
    id: str = Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")
    category: Category
    language: Language
    message: str = Field(min_length=1)
    history: list[Turn] = Field(default_factory=list)
    stage: str = "engaged"
    need_summary: str | None = None
    mode: Literal["prospect", "customer"] = "prospect"
    documents: list[EvalDocument] = Field(default_factory=list, description="документы клиента")
    erp: ErpFixture | None = Field(default=None, description="есть — у хода есть инструменты ERP")
    expect: Expect


def load_cases(directory: Path = GOLDEN_DIR) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    for path in sorted(directory.glob("*.yaml")):
        for raw in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            cases.append(GoldenCase.model_validate(raw))
    return cases

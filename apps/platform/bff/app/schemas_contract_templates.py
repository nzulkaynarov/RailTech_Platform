"""Шаблоны договоров с утверждением (ДОК-10, DECISIONS 2026-11-23).

Список, редакции, утверждение, предложение в сделке. Данные и права — в ERP (`DocumentTemplate`,
право `contract.approve_template` держателя зоны «Право»). BFF переводит ответ ERP в контракт.
"""

import datetime as dt
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas_company import ident, opt_ident, text

TemplateStatus = Literal["draft", "on_approval", "approved"]
Counterparty = Literal["client", "partner"]
Subject = Literal["supply", "services"]
Lang = Literal["ru", "uz", "en"]


class ContractTemplate(BaseModel):
    id: str
    name: str
    edition: int
    status: TemplateStatus
    counterparty: Counterparty | None
    subject: Subject | None
    approved_by: str | None
    approved_at: dt.datetime | None
    submitted_at: dt.datetime | None
    is_active: bool
    locked: bool = Field(description="Закреплённый текст: правится только новой редакцией")
    languages: list[Lang]
    updated_at: str


class ContractTemplateList(BaseModel):
    items: list[ContractTemplate]


class ContractTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    counterparty: Counterparty
    subject: Subject


class OfferedContractTemplates(BaseModel):
    """Предлагаемые в сделке шаблоны: утверждённые, вида контрагента; `default_id` — из настроек."""

    counterparty: Counterparty
    default_id: str | None
    items: list[ContractTemplate]


def _when(value: Any) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def to_contract_template(raw: Mapping[str, Any]) -> ContractTemplate:
    status = raw.get("approval_status")
    counterparty = raw.get("counterparty_kind")
    subject = raw.get("subject")
    langs = [lang for lang in raw.get("languages") or [] if lang in ("ru", "uz", "en")]
    return ContractTemplate(
        id=ident(raw.get("id")),
        name=text(raw.get("name")),
        edition=raw.get("edition") if isinstance(raw.get("edition"), int) else 1,
        status=status if status in ("draft", "on_approval", "approved") else "draft",
        counterparty=counterparty if counterparty in ("client", "partner") else None,
        subject=subject if subject in ("supply", "services") else None,
        approved_by=text(raw.get("approved_by_name")) or None,
        approved_at=_when(raw.get("approved_at")),
        submitted_at=_when(raw.get("submitted_at")),
        is_active=raw.get("is_active") is True,
        locked=raw.get("is_locked") is True,
        languages=langs or ["ru"],
        updated_at=text(raw.get("updated_at")),
    )


def to_offered(raw: Mapping[str, Any]) -> OfferedContractTemplates:
    kind = raw.get("counterparty_kind")
    return OfferedContractTemplates(
        counterparty=kind if kind in ("client", "partner") else "client",
        default_id=opt_ident(raw.get("default_id")),
        items=[to_contract_template(r) for r in raw.get("items") or [] if isinstance(r, dict)],
    )


# --- ШАБЛ-1: текст шаблона в Word и обратно ---------------------------------------------


class WordSegment(BaseModel):
    op: Literal["equal", "del", "ins"]
    text: str


class WordChange(BaseModel):
    point: str = Field(description="Номер пункта в начале абзаца; пусто, если номера нет")
    kind: Literal["changed", "added", "removed"]
    ours: str
    theirs: str
    segments: list[WordSegment]


class WordChangeSummary(BaseModel):
    changed: list[str]
    added: list[str]
    removed: list[str]
    total: int
    more: int


class WordMissingBlock(BaseModel):
    code: str
    label: str


class TemplateWordCheck(BaseModel):
    """Что изменится, если принять загруженный Word. Ничего не сохранено; `base` — в «Принять»."""

    unchanged: bool
    formatting_only: bool = Field(description="Текст тот же, изменилось только оформление")
    can_apply: bool
    locked: bool = Field(
        description="Закреплённый шаблон договора: правки — только в новой редакции"
    )
    base: str
    images_dropped: int
    unknown_placeholders: list[str]
    missing_blocks: list[WordMissingBlock]
    summary: WordChangeSummary
    items: list[WordChange]


def to_word_check(raw: Mapping[str, Any]) -> TemplateWordCheck:
    changes: dict[str, Any] = raw["changes"] if isinstance(raw.get("changes"), dict) else {}
    summary: dict[str, Any] = changes["summary"] if isinstance(changes.get("summary"), dict) else {}

    def points(key: str) -> list[str]:
        return [str(p) for p in summary.get(key) or []]

    items = [
        WordChange(
            point=text(i.get("point")),
            kind=i.get("kind") if i.get("kind") in ("changed", "added", "removed") else "changed",
            ours=text(i.get("ours")),
            theirs=text(i.get("theirs")),
            segments=[
                WordSegment(op=g["op"], text=text(g.get("text")))
                for g in i.get("segments") or []
                if isinstance(g, dict) and g.get("op") in ("equal", "del", "ins")
            ],
        )
        for i in changes.get("items") or []
        if isinstance(i, dict)
    ]
    return TemplateWordCheck(
        unchanged=raw.get("unchanged") is True,
        formatting_only=raw.get("formatting_only") is True,
        can_apply=raw.get("can_apply") is True,
        locked=raw.get("locked") is True,
        base=text(raw.get("base")),
        images_dropped=raw.get("images_dropped")
        if isinstance(raw.get("images_dropped"), int)
        else 0,
        unknown_placeholders=[str(c) for c in raw.get("unknown_placeholders") or []],
        missing_blocks=[
            WordMissingBlock(code=text(b.get("code")), label=text(b.get("label")))
            for b in raw.get("missing_blocks") or []
            if isinstance(b, dict)
        ],
        summary=WordChangeSummary(
            changed=points("changed"),
            added=points("added"),
            removed=points("removed"),
            total=summary.get("total") if isinstance(summary.get("total"), int) else len(items),
            more=summary.get("more") if isinstance(summary.get("more"), int) else 0,
        ),
        items=items,
    )

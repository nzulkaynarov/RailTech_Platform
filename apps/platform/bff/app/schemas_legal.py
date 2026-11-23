"""Модели «Настройки · Оферта и политика» (ДВ-5): схемы `Legal*` из platform-bff.yaml.

ERP `settings/legal-editions/` и `settings/legal-acceptances/`: редакции документов Кабинета
на трёх языках, публикация и журнал акцептов. Право решает ERP (`settings.edit`); BFF проверяет
раздел `company.settings` и переводит идентификаторы в строки.
"""

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from app.schemas_company import Body, Patch, ident, text

LegalKind = Literal["privacy", "terms"]
EditionStatus = Literal["draft", "current", "retired"]
Language = Literal["ru", "uz", "en"]


class Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LegalLangText(Out):
    ru: str
    uz: str
    en: str


class LegalSection(Out):
    title: LegalLangText
    body: LegalLangText


class LegalContent(Out):
    title: LegalLangText
    lead: LegalLangText
    sections: list[LegalSection]


class LegalEditionRow(Out):
    id: str
    kind: LegalKind
    label: str
    status: EditionStatus
    created_at: str
    published_at: str | None = None
    published_by: str | None = None
    retired_at: str | None = None
    acceptances_count: int


class LegalEditionList(Out):
    items: list[LegalEditionRow]


class LegalEditionDetail(LegalEditionRow):
    content: LegalContent
    rendered: LegalContent


class LegalEditionCreate(Body):
    kind: LegalKind


class LegalEditionUpdate(Patch):
    label: str | None = None
    content: LegalContent | None = None


class LegalPerson(Out):
    id: str
    name: str
    email: str


class LegalCompany(Out):
    id: str
    name: str


class LegalAcceptance(Out):
    id: str
    accepted_at: str
    kind: LegalKind
    edition: str
    edition_id: str
    language: Language
    auth_method: str | None = None
    contact: LegalPerson
    company: LegalCompany


class LegalAcceptancePage(Out):
    items: list[LegalAcceptance]
    total: int
    page: int
    page_size: int


def _lang(node: Any) -> dict[str, str]:
    node = node if isinstance(node, Mapping) else {}
    return {lang: text(node.get(lang)) for lang in ("ru", "uz", "en")}


def _content(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, Mapping) else {}
    return {
        "title": _lang(raw.get("title")),
        "lead": _lang(raw.get("lead")),
        "sections": [
            {"title": _lang(s.get("title")), "body": _lang(s.get("body"))}
            for s in raw.get("sections") or []
            if isinstance(s, Mapping)
        ],
    }


def _row(raw: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": ident(raw["id"]),
        "kind": raw["kind"],
        "label": text(raw.get("label")),
        "status": raw["status"],
        "created_at": text(raw.get("created_at")),
        "published_at": raw.get("published_at") or None,
        "published_by": text(raw.get("published_by")) or None,
        "retired_at": raw.get("retired_at") or None,
        "acceptances_count": int(raw.get("acceptances_count") or 0),
    }


def to_edition_list(raw: Mapping[str, Any]) -> LegalEditionList:
    return LegalEditionList(items=[LegalEditionRow(**_row(r)) for r in raw.get("results") or []])


def to_edition(raw: Mapping[str, Any]) -> LegalEditionDetail:
    return LegalEditionDetail(
        **_row(raw), content=_content(raw.get("content")), rendered=_content(raw.get("rendered"))
    )


def to_acceptance_page(raw: Mapping[str, Any], *, page: int, page_size: int) -> LegalAcceptancePage:
    items = []
    for r in raw.get("results") or []:
        contact, company = r.get("contact") or {}, r.get("company") or {}
        items.append(
            LegalAcceptance(
                id=ident(r["id"]),
                accepted_at=text(r.get("accepted_at")),
                kind=r["kind"],
                edition=text(r.get("edition")),
                edition_id=ident(r["edition_id"]),
                language=r["language"],
                auth_method=text(r.get("auth_method")) or None,
                contact=LegalPerson(
                    id=ident(contact.get("id")),
                    name=text(contact.get("name")),
                    email=text(contact.get("email")),
                ),
                company=LegalCompany(id=ident(company.get("id")), name=text(company.get("name"))),
            )
        )
    return LegalAcceptancePage(
        items=items, total=int(raw.get("count") or 0), page=page, page_size=page_size
    )

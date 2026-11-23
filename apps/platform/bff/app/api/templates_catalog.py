"""Каталог шаблонов всех доменов (план 2026-11-12 п. 2.7; исследование 2026-11-11
«Документы и шаблоны» §3, TPL-1).

Одна таблица «Настройки · Шаблоны»: шаблоны документов и писем ERP, резолюций EDS и быстрые
ответы бота CRM. Строки «КП» нет: у КП нет шаблона, а «Условия КП» — настройки (ДОК-13);
строка вернётся с ДОК-16.
BFF собирает список из API доменов от имени сотрудника,
как ленты: источник без раздела у ролей не опрашивается, упавший — помечен в `sources`.
Строка ведёт в нынешний редактор. Шаблоны хранит домен-владелец; общий ресурс `/templates` у
доменов появится вместе с вариантами по языкам (TPL-2, TPL-4).
"""

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.deps import Authed, require_any_section
from app.feeds.feed import Feed, rows
from app.feeds.models import Sources
from app.feeds.view import roles_of_view
from app.rbac import Access, allows
from app.schemas_company import TEMPLATE_KIND_FROM_ERP

router = APIRouter(tags=["templates"])

CatalogAuthed = Annotated[Authed, Depends(require_any_section)]

TemplateKind = Literal[
    "quote",
    "contract",
    "invoice",
    "act",
    "receipt",
    "delivery_note",
    "letter",
    "memo",
    "report",
    "custom",
    "email",
    "resolution",
    "reply",
]
Lang = Literal["ru", "uz", "en"]
LANGS: tuple[Lang, ...] = ("ru", "uz", "en")


class TemplateRow(BaseModel):
    id: str
    kind: TemplateKind
    name: str
    domain: Literal["erp", "eds", "crm"]
    languages: list[Lang]
    origin: Literal["builtin", "custom"]
    active: bool
    updated_at: str | None = None
    path: str


class TemplateCatalog(BaseModel):
    items: list[TemplateRow]
    sources: Sources


_VARIABLE = re.compile(r"\{\{\s*[\w.]+\s*\}\}")


def _title(subject: str) -> str:
    """Тема письма как название: переменные шаблона `{{number}}` — многоточием."""
    return " ".join(_VARIABLE.sub("…", subject).split())


def _langs(values: Any) -> list[Lang]:
    present = {str(v) for v in values}
    return [lang for lang in LANGS if lang in present]


def _documents(payload: Any) -> list[TemplateRow]:
    out: list[TemplateRow] = []
    for row in rows(payload):
        kind = TEMPLATE_KIND_FROM_ERP.get(
            str(row.get("kind_code") or row.get("kind") or ""), "custom"
        )
        out.append(
            TemplateRow(
                id=f"erp.document:{row.get('id')}",
                kind=kind,
                name=str(row.get("name") or ""),
                domain="erp",
                languages=["ru"],  # варианты по языкам — TPL-4 и DOC-1…3
                origin="builtin" if row.get("is_sample") else "custom",
                active=bool(row.get("is_active", True)),
                updated_at=str(row.get("updated_at") or "") or None,
                path=f"/admin/templates?tab=documents&template={row.get('id')}",
            )
        )
    return out


def _emails(payload: Any) -> list[TemplateRow]:
    """Письма ERP: одна строка на ключ письма, языки — у каких вариантов ключа есть запись."""
    by_key: dict[str, list[dict[str, Any]]] = {}
    for row in rows(payload):
        by_key.setdefault(str(row.get("key") or ""), []).append(row)
    out: list[TemplateRow] = []
    for key, group in sorted(by_key.items()):
        first = next((r for r in group if r.get("language") == "ru"), group[0])
        out.append(
            TemplateRow(
                id=f"erp.email:{key}",
                kind="email",
                name=_title(str(first.get("subject") or "")) or key,
                domain="erp",
                languages=_langs(r.get("language") for r in group),
                origin="custom",
                active=any(bool(r.get("is_active", True)) for r in group),
                updated_at=max((str(r.get("updated_at") or "") for r in group), default="") or None,
                path=f"/admin/templates?tab=emails&template={first.get('id')}",
            )
        )
    return out


def _resolutions(payload: Any) -> list[TemplateRow]:
    return [
        TemplateRow(
            id=f"eds.resolution:{row.get('id')}",
            kind="resolution",
            name=str(row.get("name") or ""),
            domain="eds",
            languages=[],  # резолюция пишется на языке директора, вариантов нет
            origin="custom",
            active=True,
            path=f"/admin/resolutions?template={row.get('id')}",
        )
        for row in rows(payload)
    ]


def _letters(payload: Any) -> list[TemplateRow]:
    """Письма и служебки на бланке EDS (TPL-4): варианты по языкам, встроенные и свои."""
    out: list[TemplateRow] = []
    for row in rows(payload):
        kind = "memo" if row.get("kind") == "memo" else "letter"
        out.append(
            TemplateRow(
                id=f"eds.template:{row.get('id')}",
                kind=kind,
                name=str(row.get("name") or ""),
                domain="eds",
                languages=_langs(row.get("languages") or []),
                origin="builtin" if row.get("origin") == "builtin" else "custom",
                active=bool(row.get("active", True)),
                updated_at=str(row.get("updated_at") or "") or None,
                path=f"/admin/templates?tab=letters&template={row.get('id')}",
            )
        )
    return out


def _replies(payload: Any) -> list[TemplateRow]:
    out: list[TemplateRow] = []
    for row in rows(payload):
        raw = row.get("text")
        text: dict[str, Any] = raw if isinstance(raw, dict) else {}
        out.append(
            TemplateRow(
                id=f"crm.reply:{row.get('id')}",
                kind="reply",
                name=str(row.get("title") or ""),
                domain="crm",
                languages=_langs(k for k, v in text.items() if str(v or "").strip()),
                origin="custom",
                active=True,
                updated_at=str(row.get("updated_at") or "") or None,
                path=f"/admin/telegram?tab=templates&template={row.get('id')}",
            )
        )
    return out


async def _none() -> list[TemplateRow]:
    return []


async def catalog(feed: Feed, access: Access) -> TemplateCatalog:
    company = allows(access, "company.settings", "read")
    resolutions = (
        allows(access, "eds.inbox", "full")
        or allows(access, "eds.inbox.register", "full")
        or allows(access, "admin", "read")
    )
    # Ответы бота правит страница «Telegram» (раздел `admin.system`): без неё у строки нет места, куда вести, — строк нет
    replies = allows(access, "admin.system", "read")
    letters = (
        allows(access, "eds.memo.create", "read")
        or allows(access, "eds.inbox.register", "full")
        or allows(access, "admin", "read")
    )

    def source(
        enabled: bool,
        backend: Literal["erp", "eds", "crm"],
        path: str,
        build: Callable[[Any], list[TemplateRow]],
    ) -> Awaitable[list[TemplateRow]]:
        async def load() -> list[TemplateRow]:
            return build(
                await feed.get(backend, path, {"page_size": 200} if backend == "erp" else None)
            )

        return load() if enabled else _none()

    parts = await asyncio.gather(
        source(company, "erp", "/api/v1/crm/document-templates/", _documents),
        source(company, "erp", "/api/v1/settings/email-templates/", _emails),
        source(letters, "eds", "/api/v1/templates", _letters),
        source(resolutions, "eds", "/api/v1/resolution-templates", _resolutions),
        source(replies, "crm", "/api/v1/reply-templates", _replies),
    )
    items = [row for part in parts for row in part]
    return TemplateCatalog(items=items, sources=feed.sources)


@router.get(
    "/templates",
    response_model=TemplateCatalog,
    response_model_exclude_none=True,
    operation_id="listTemplateCatalog",
)
async def list_template_catalog(authed: CatalogAuthed) -> TemplateCatalog:
    return await catalog(Feed(authed), roles_of_view(authed, None).access)

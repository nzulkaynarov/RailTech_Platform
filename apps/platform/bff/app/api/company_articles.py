"""Статьи компании (tag `company-articles`, W18A-P5, B-079).

Внутренние инструкции «как у нас принято»: админ пишет их в «Настройки · Статьи компании»,
все сотрудники читают опубликованные в Помощи рядом с продуктовыми статьями. Решения и данные —
в CRM (ADR-0015), токеном самого сотрудника: опубликованные — любому сотруднику, все с черновиками —
права раздела `admin` (директор читает, администратор правит; проверяют и BFF, и CRM). BFF переводит
ошибки CRM в формат `Error`.
"""

from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Path, Response, status

from app.deps import Authed, require, require_any_section
from app.errors import PlatformError, backend_reason, from_backend
from app.schemas_company_articles import (
    CompanyArticle,
    CompanyArticleCreate,
    CompanyArticleList,
    CompanyArticleUpdate,
    to_article,
)

router = APIRouter(tags=["company-articles"])

CRM = "/api/v1/company-articles"
CRM_MINE = "/api/v1/me/company-articles"
Reader = Annotated[Authed, Depends(require_any_section)]
AdminRead = Annotated[Authed, Depends(require("admin", "read"))]
AdminWrite = Annotated[Authed, Depends(require("admin", "full"))]
ArticleId = Annotated[int, Path(ge=1, description="Идентификатор статьи компании")]

_MESSAGES = {
    "article_title_empty": "Напишите заголовок.",
    "article_title_too_long": "Заголовок длиннее 200 символов: сократите его.",
    "article_body_empty": "Напишите текст статьи.",
    "article_body_too_long": "Текст длиннее 20000 символов: сократите его.",
    "article_language_unknown": "Выберите язык из списка.",
}
_FIELDS = {"title": "title", "body": "body", "language": "language"}


def _translate(response: httpx.Response) -> PlatformError:
    """4xx CRM -> `Error`: ошибка значения — 422 с `details.fields` и `details.reason`."""
    reason = backend_reason(response)
    if response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT and reason in _MESSAGES:
        field = _field_of(response)
        return PlatformError(
            "VALIDATION_FAILED",
            _MESSAGES[reason],
            status_code=422,
            source="crm",
            details={"fields": [field] if field else [], "reason": reason},
        )
    err = from_backend("crm", response)
    if reason and err.body.details is not None:
        err.body.details["reason"] = reason
    return err


def _field_of(response: httpx.Response) -> str | None:
    try:
        field = response.json()["details"]["field"]
    except (ValueError, KeyError, TypeError):
        return None
    return _FIELDS.get(field) if isinstance(field, str) else None


def _json(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        raise _translate(response)
    return response.json()


@router.get(
    "/help/company-articles",
    response_model=CompanyArticleList,
    response_model_exclude_none=True,
    operation_id="listCompanyArticles",
)
async def list_company_articles(authed: Reader) -> CompanyArticleList:
    body = _json(await authed.call("crm", "GET", CRM_MINE))
    return CompanyArticleList(items=[to_article(r) for r in body["items"]])


@router.get(
    "/admin/company-articles",
    response_model=CompanyArticleList,
    response_model_exclude_none=True,
    operation_id="listAdminCompanyArticles",
)
async def list_admin_company_articles(authed: AdminRead) -> CompanyArticleList:
    body = _json(await authed.call("crm", "GET", CRM))
    return CompanyArticleList(items=[to_article(r) for r in body["items"]])


@router.post(
    "/admin/company-articles",
    response_model=CompanyArticle,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    operation_id="createCompanyArticle",
)
async def create_company_article(body: CompanyArticleCreate, authed: AdminWrite) -> CompanyArticle:
    return to_article(_json(await authed.call("crm", "POST", CRM, json=body.model_dump())))


@router.patch(
    "/admin/company-articles/{id}",
    response_model=CompanyArticle,
    response_model_exclude_none=True,
    operation_id="updateCompanyArticle",
)
async def update_company_article(
    id: ArticleId, body: CompanyArticleUpdate, authed: AdminWrite
) -> CompanyArticle:
    payload = body.model_dump(exclude_none=True)
    return to_article(_json(await authed.call("crm", "PATCH", f"{CRM}/{id}", json=payload)))


@router.post(
    "/admin/company-articles/{id}/publish",
    response_model=CompanyArticle,
    response_model_exclude_none=True,
    operation_id="publishCompanyArticle",
)
async def publish_company_article(id: ArticleId, authed: AdminWrite) -> CompanyArticle:
    return to_article(_json(await authed.call("crm", "POST", f"{CRM}/{id}/publish")))


@router.post(
    "/admin/company-articles/{id}/unpublish",
    response_model=CompanyArticle,
    response_model_exclude_none=True,
    operation_id="unpublishCompanyArticle",
)
async def unpublish_company_article(id: ArticleId, authed: AdminWrite) -> CompanyArticle:
    return to_article(_json(await authed.call("crm", "POST", f"{CRM}/{id}/unpublish")))


@router.delete(
    "/admin/company-articles/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCompanyArticle",
)
async def delete_company_article(id: ArticleId, authed: AdminWrite) -> Response:
    response = await authed.call("crm", "DELETE", f"{CRM}/{id}")
    if response.status_code >= 400:
        raise _translate(response)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

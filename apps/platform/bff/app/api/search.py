"""Сквозной поиск ⌘K (контракт: tag `search`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.deps import Authed, require_any_section
from app.feeds import search as service
from app.feeds.feed import Feed
from app.feeds.models import SearchResult
from app.feeds.view import roles_of_view

router = APIRouter(tags=["search"])

# Поиск открыт любой роли с разделами: группы и результаты фильтруются по разделам «вида» (R-2).
SearchAuthed = Annotated[Authed, Depends(require_any_section)]


@router.get(
    "/search", response_model=SearchResult, response_model_exclude_none=True, operation_id="search"
)
async def search(
    authed: SearchAuthed,
    q: Annotated[str, Query(min_length=2, max_length=100)],
) -> SearchResult:
    return await service.search(Feed(authed), roles_of_view(authed, None).access, q)

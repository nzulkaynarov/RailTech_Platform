"""Тестовые компании (ТЕСТ-1, DECISIONS 2026-11-27): отметка `Company.is_test` и выборки «без тестовых».

Тестовая компания ничего не теряет — ни записей, ни писем, ни входа в кабинет, — но не мешает работе: из рабочих списков,
счётчиков, панелей, очередей и отчётов она уходит по умолчанию и видна по фильтру «Тестовые» (`?test=only`). Одно место
правды для всех выборок: `scope` для списков (читает `?test=`) и `hide` для счётчиков и отчётов (тестовых нет всегда).
Карточка и открытие по номеру тестовую компанию не прячут — только списки и агрегаты.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Mapping, Optional

from django.db.models import QuerySet

#: `?test=only` — только тестовые («Тестовые»); `?test=all` — все вместе; без параметра — без тестовых
ONLY = "only"
ALL = "all"


# ТЕСТ-2: «Показывать тестовые» — сотрудник включил переключатель в профиле, BFF добавляет `?test=all` к чтению. Признак
# держится на время запроса (`TestScopeMiddleware`), и `hide` пропускает тестовые компании везде — и в списках, и в счётчиках.
_show_all: ContextVar[bool] = ContextVar("show_all_test_companies", default=False)


def show_all() -> bool:
    return _show_all.get()


def cache_suffix() -> str:
    """Для ключей кэша агрегатов: ответ с тестовыми компаниями и без них — разные."""
    return ":test" if show_all() else ""


class TestScopeMiddleware:
    """`?test=all` на запросе -> `show_all()` до конца запроса (ТЕСТ-2); решает, кому его добавлять, BFF по профилю."""

    __test__ = False  # не тест-класс для pytest

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _show_all.set(request.GET.get("test") == ALL)
        try:
            return self.get_response(request)
        finally:
            _show_all.reset(token)


def mode(params: Optional[Mapping]) -> str:
    value = (params.get("test") if params else None) or ""
    return value if value in (ONLY, ALL) else ""


def hide(queryset: QuerySet, path: str = "company") -> QuerySet:
    """Без тестовых компаний: `path` — путь к компании (`company`, `deal__company`, пустой — сама компания).

    `exclude` безопасен к пустой связи: запись без компании остаётся."""
    if show_all():
        return queryset
    field = f"{path}__is_test" if path else "is_test"
    return queryset.exclude(**{field: True})


def only(queryset: QuerySet, path: str = "company") -> QuerySet:
    field = f"{path}__is_test" if path else "is_test"
    return queryset.filter(**{field: True})


def scope(queryset: QuerySet, params: Optional[Mapping], path: str = "company") -> QuerySet:
    """Список по `?test=`: по умолчанию без тестовых, `only` — только они, `all` — всё."""
    wanted = mode(params)
    if wanted == ALL:
        return queryset
    return only(queryset, path) if wanted == ONLY else hide(queryset, path)


def flag(company) -> dict:
    """ТЕСТ-2: `{"is_test": True}` для строки тестовой компании, пока включён `?test=all`; иначе пусто (поле не добавляется)."""
    return {"is_test": True} if show_all() and company is not None and company.is_test else {}


def tag(data, queryset: QuerySet, path: str = "company", key: str = "id"):
    """ТЕСТ-2: при `?test=all` строки тестовых компаний получают `is_test: true` — клиент рисует метку «Тестовая».

    `data` — тело ответа списка (`{"results": [...]}` или голый массив); `key` — поле строки с ключом модели `queryset`.
    Без `?test=all` ничего не делает: тестовых строк в ответе нет. Один запрос на страницу."""
    if not show_all():
        return data
    rows = data.get("results") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return data
    ids = [row.get(key) for row in rows if isinstance(row, dict) and row.get(key) is not None]
    marked = (
        set(only(queryset.model._default_manager.filter(pk__in=ids), path).values_list("pk", flat=True))
        if ids
        else set()
    )
    for row in rows:
        if isinstance(row, dict):
            row["is_test"] = row.get(key) in marked
    return data


class ListScopeMixin:
    """Миксин вьюсета: список (`action == "list"`) — без тестовых компаний, `?test=only|all` меняет выборку.

    `test_company_path` — путь к компании от модели вьюсета (`deal__company`). Карточка, действия и открытие по номеру
    выборку не сужают: тестовую сделку можно открыть и довести до конца."""

    test_company_path = "company"
    test_company_actions = ("list",)

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        tag(response.data, self.get_queryset(), self.test_company_path)  # ТЕСТ-2: метка «Тестовая» в строках
        return response

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if getattr(self, "action", None) in self.test_company_actions:
            queryset = scope(queryset, self.request.query_params, self.test_company_path)
        return queryset

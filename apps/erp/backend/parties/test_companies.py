"""Тестовые компании (ТЕСТ-1, DECISIONS 2026-11-27): отметка `Company.is_test` и выборки «без тестовых».

Тестовая компания ничего не теряет — ни записей, ни писем, ни входа в кабинет, — но не мешает работе: из рабочих списков,
счётчиков, панелей, очередей и отчётов она уходит по умолчанию и видна по фильтру «Тестовые» (`?test=only`). Одно место
правды для всех выборок: `scope` для списков (читает `?test=`) и `hide` для счётчиков и отчётов (тестовых нет всегда).
Карточка и открытие по номеру тестовую компанию не прячут — только списки и агрегаты.
"""

from __future__ import annotations

from typing import Mapping, Optional

from django.db.models import QuerySet

#: `?test=only` — только тестовые («Тестовые»); `?test=all` — все вместе; без параметра — без тестовых
ONLY = "only"
ALL = "all"


def mode(params: Optional[Mapping]) -> str:
    value = (params.get("test") if params else None) or ""
    return value if value in (ONLY, ALL) else ""


def hide(queryset: QuerySet, path: str = "company") -> QuerySet:
    """Без тестовых компаний: `path` — путь к компании (`company`, `deal__company`, пустой — сама компания).

    `exclude` безопасен к пустой связи: запись без компании остаётся."""
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


class ListScopeMixin:
    """Миксин вьюсета: список (`action == "list"`) — без тестовых компаний, `?test=only|all` меняет выборку.

    `test_company_path` — путь к компании от модели вьюсета (`deal__company`). Карточка, действия и открытие по номеру
    выборку не сужают: тестовую сделку можно открыть и довести до конца."""

    test_company_path = "company"
    test_company_actions = ("list",)

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        if getattr(self, "action", None) in self.test_company_actions:
            queryset = scope(queryset, self.request.query_params, self.test_company_path)
        return queryset

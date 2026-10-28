"""Поиск сделок `?search=` (ERP-09): номер ЗВ/ПР — по году и NNN, иначе подстрока номера, названия и компании."""

from django.db.models import Q
from rest_framework.filters import SearchFilter
from sales.services import deal_numbers


class DealSearchFilter(SearchFilter):
    """`ЗВ-2026-104` находит и `ПР-2026-104` (тот же NNN после принятия КП), `zv 2026 4` — `ЗВ-2026-004`.

    Запрос не номер — обычный `SearchFilter` по `search_fields` вида (номер, название, компания).
    """

    def filter_queryset(self, request, queryset, view):
        text = request.query_params.get(self.search_param, "")
        parsed = deal_numbers.parse_query(text)
        if parsed is None:
            return super().filter_queryset(request, queryset, view)
        year, seq = parsed
        return queryset.filter(Q(number_year=year, number_seq=seq) | Q(title__icontains=text.strip()))

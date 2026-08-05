"""Фильтр-бэкенды каталога.

Живут отдельно от вьюсета: это способ ЧИТАТЬ выборку, а не бизнес-логика (Rule 8).
"""

from rest_framework import filters


class StableOrderingFilter(filters.OrderingFilter):
    """`OrderingFilter` + гарантированно ОДНОЗНАЧНЫЙ порядок.

    Серверная пагинация (волна R1) отдаёт страницы отдельными запросами, а Postgres при
    равных ключах сортировки волен вернуть строки в любом порядке. Сортировка по
    `demand_count` или `status` — а в очереди наполнения ключи совпадают у десятков карточек —
    без вторичного ключа приводит к тому, что одна и та же карточка попадает и на первую, и
    на вторую страницу, а другая не попадает никуда. Эталон тот же, что у курсорной пагинации
    DRF и у keyset-пагинации в целом: сортировка обязана заканчиваться уникальным полем.

    `pk` дописывается только когда сортировка вообще задана — при `ordering=<неизвестное поле>`
    базовый класс возвращает пустой порядок, и вьюсет сохраняет свою собственную сортировку
    (в частности легаси-ветку `?order=demand`).
    """

    def get_ordering(self, request, queryset, view):
        ordering = super().get_ordering(request, queryset, view)
        if not ordering:
            return ordering
        if any(field.lstrip("-") == "pk" for field in ordering):
            return ordering
        return list(ordering) + ["pk"]

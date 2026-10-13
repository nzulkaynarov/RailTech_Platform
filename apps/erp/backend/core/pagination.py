"""Пагинация по умолчанию: клиент МОЖЕТ попросить больше строк (N2, M1 аудита).

До N2 `PAGE_SIZE=20` был жёстким: фронтенд слал `page_size=200` (очередь номенклатуры,
worklist переклассификации), DRF молча игнорировал параметр — и 21-й кандидат был недостижим
без пейджера. `max_page_size` держит верхнюю границу, чтобы «дай всё» не превращалось в
неограниченную выборку.
"""

from rest_framework.pagination import PageNumberPagination


class DefaultPageNumberPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 200

"""Переходный ре-экспорт (DECISIONS 2026-10-14, M1-ERP-06): ИИ-разбор файла, сопоставление с каталогом и нормализация имён — ``ai.services.intake`` / ``ai.services.matching``."""

from ai.services.intake import ITEM_SCHEMA, RESULT_SCHEMA, extract_request_items, normalize_items  # noqa: F401
from ai.services.matching import (  # noqa: F401
    MATCH_RESULT_SCHEMA,
    canonicalize_names,
    match_lines_to_catalog,
    rank_candidates,
    shortlist_products,
)
from ai.services.payloads import chunk_lines, file_to_payload  # noqa: F401

__all__ = [
    "ITEM_SCHEMA",
    "RESULT_SCHEMA",
    "extract_request_items",
    "normalize_items",
    "MATCH_RESULT_SCHEMA",
    "canonicalize_names",
    "match_lines_to_catalog",
    "rank_candidates",
    "shortlist_products",
    "chunk_lines",
    "file_to_payload",
]

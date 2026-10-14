"""Переходный ре-экспорт (DECISIONS 2026-10-14, M1-ERP-06): черновик карточки — ``ai.services.enrich``."""

from ai.services.enrich import ENRICH_RESULT_SCHEMA, enrich_product  # noqa: F401

__all__ = ["ENRICH_RESULT_SCHEMA", "enrich_product"]

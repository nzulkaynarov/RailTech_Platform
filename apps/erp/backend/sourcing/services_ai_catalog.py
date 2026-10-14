"""Переходный ре-экспорт (DECISIONS 2026-10-14, M1-ERP-06): строки прайс-листа — ``ai.services.price_list``."""

from ai.services.price_list import MAX_AI_PRICE_ROWS, PRICE_RESULT_SCHEMA, extract_price_rows  # noqa: F401

__all__ = ["MAX_AI_PRICE_ROWS", "PRICE_RESULT_SCHEMA", "extract_price_rows"]

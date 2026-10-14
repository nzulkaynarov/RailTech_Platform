"""Переходный ре-экспорт (DECISIONS 2026-10-14, M1-ERP-06): советы по качеству строк запроса — ``ai.services.preflight``."""

from ai.services.preflight import MAX_PREFLIGHT_LINES, PREFLIGHT_RESULT_SCHEMA, pre_flight_check  # noqa: F401

__all__ = ["MAX_PREFLIGHT_LINES", "PREFLIGHT_RESULT_SCHEMA", "pre_flight_check"]

"""Переходный ре-экспорт (DECISIONS 2026-10-14, M1-ERP-06): запрос из свободного текста — ``ai.services.compose``."""

from ai.services.compose import COMPOSE_RESULT_SCHEMA, MAX_TEXT_CHARS, build_request_from_text  # noqa: F401

__all__ = ["COMPOSE_RESULT_SCHEMA", "MAX_TEXT_CHARS", "build_request_from_text"]

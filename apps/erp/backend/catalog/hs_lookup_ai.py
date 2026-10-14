"""Переходный ре-экспорт (DECISIONS 2026-10-14, M1-ERP-06): ИИ-подбор кода ТН ВЭД — ``ai.services.hs_lookup``."""

from ai.services.hs_lookup import classify_products, lookup_hs_code  # noqa: F401

__all__ = ["classify_products", "lookup_hs_code"]

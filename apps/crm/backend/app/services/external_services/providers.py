"""Алиас → провайдер для реестра (ADR-0024): из шлюза, а при его недоступности — из значений по
умолчанию (`litellm.models.yaml`), чтобы строки вендоров не пропадали, когда шлюз лежит."""

from functools import lru_cache
from pathlib import Path

import structlog

from app.integrations.litellm_admin import load_defaults
from app.integrations.litellm_catalog import ModelCatalog

logger = structlog.get_logger(__name__)


@lru_cache
def _defaults(path: Path) -> dict[str, str | None]:
    try:
        models = load_defaults(path)
    except (OSError, ValueError, KeyError) as exc:
        logger.info("litellm_defaults_unavailable", error=type(exc).__name__)
        return {}
    return {
        alias: d.model.split("/", 1)[0] if "/" in d.model else None for alias, d in models.items()
    }


async def providers(catalog: ModelCatalog, defaults: Path | None) -> dict[str, str | None]:
    entries = await catalog.entries()
    if entries:
        return {alias: e.provider for alias, e in entries.items()}
    return dict(_defaults(defaults)) if defaults is not None else {}

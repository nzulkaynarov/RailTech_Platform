"""МХИК (ИКПУ) — классификатор товаров Налогового комитета (план 1.8; исследование 2026-11-11-reference-data §B3).

Поиск по слову — открытый адрес tasnif.soliq.uz без ключа (`/api/cls-api/mxik/search/by-params`). Документации и условий
у адреса нет, поэтому классификатор — подсказка: недоступен — `MxikUnavailable`, и код вводится вручную. Хранится у
товара только выбранное: код, название, единица и упаковка.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)

SEARCH_PATH = "/api/cls-api/mxik/search/by-params"
MAX_RESULTS = 10
CODE_LENGTH = 17


class MxikUnavailable(Exception):
    """Классификатор не ответил или ответил не так: код вводится вручную."""


def normalize_code(value: Any) -> str:
    """Код МХИК — ровно 17 цифр; пусто — снять код. Иначе ``ValueError``."""
    text = str(value or "").strip()
    if not text:
        return ""
    if not (text.isdigit() and len(text) == CODE_LENGTH):
        raise ValueError("mxik code must be 17 digits")
    return text


def _row(raw: dict[str, Any]) -> dict[str, Any] | None:
    code = str(raw.get("mxikCode") or "").strip()
    if not (code.isdigit() and len(code) == CODE_LENGTH):
        return None
    packages = [p for p in raw.get("packages") or [] if isinstance(p, dict)]
    package = packages[0] if packages else {}
    return {
        "code": code,
        "name": str(raw.get("mxikName") or raw.get("subPositionName") or raw.get("positionName") or "")[:500],
        "group": str(raw.get("groupName") or raw.get("className") or "")[:300],
        "unit": str(raw.get("unitName") or package.get("unitName") or "")[:100],
        "package": str(package.get("nameRu") or package.get("name") or "")[:200],
    }


def search(text: str, *, lang: str = "ru") -> list[dict[str, Any]]:
    """До 10 позиций классификатора по слову или коду. Недоступен — ``MxikUnavailable``."""
    query = (text or "").strip()
    if len(query) < 2:
        return []
    base = getattr(settings, "MXIK_BASE_URL", "https://tasnif.soliq.uz").rstrip("/")
    try:
        response = httpx.get(
            f"{base}{SEARCH_PATH}",
            params={
                "searchText": query[:100],
                "size": MAX_RESULTS,
                "page": 0,
                "lang": "uz_latn" if lang == "uz" else "ru",
            },
            timeout=getattr(settings, "MXIK_TIMEOUT_S", 8.0),
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("MXIK classifier unavailable: %s", exc.__class__.__name__)
        raise MxikUnavailable from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("content") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise MxikUnavailable
    rows = [row for row in (_row(item) for item in items if isinstance(item, dict)) if row]
    return rows[:MAX_RESULTS]

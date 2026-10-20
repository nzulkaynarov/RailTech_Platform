"""Catalog integration search service (CONTRACTS §2, M3-ERP-01).

Использует модуль `catalog.published` — единственный путь карточки наружу.
В режиме `lead` отдаёт перечень без цен, наличия и сроков.
В режиме `client` — с ценой-витриной и статусом наличия.
"""

from __future__ import annotations

from typing import Any, Dict, List

from catalog.published import project, published_products


def search_published_catalog(query: str, mode: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Поиск по опубликованному слою каталога."""
    clean_q = str(query or "").strip()
    safe_limit = max(1, min(int(limit or 10), 50))

    qs = published_products().filter(name__icontains=clean_q)[:safe_limit]
    items = []
    for p in qs:
        proj = project(p, mode=mode)
        item: Dict[str, Any] = {
            "erp_product_id": proj["id"],
            "kind": proj["kind"],
            "name": proj["name"],
            "description": proj["description"],
            "unit": proj["unit"],
        }
        if mode == "client":
            item["price"] = proj.get("price")
            item["availability"] = proj.get("availability")
            item["lead_time_days"] = proj.get("lead_time_days")
        items.append(item)

    return items

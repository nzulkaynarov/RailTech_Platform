"""Политика каталога компании: видимость цен по умолчанию и порог публикации (M1-ERP-07).

Источник — `parties.CompanySettings` компании-владельца карточки (ARCHITECTURE §7: «ERP →
Настройки → политики каталога»). Чтение НЕ создаёт строку настроек: нет строки — действуют
умолчания продукта («по запросу», порог 100 %), как и у других настроек компании.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import DEFAULT_PUBLISH_THRESHOLD, PriceVisibility


@dataclass(frozen=True)
class CatalogPolicy:
    price_visibility: str = PriceVisibility.ON_REQUEST
    publish_threshold: int = DEFAULT_PUBLISH_THRESHOLD


DEFAULT_POLICY = CatalogPolicy()


def load_policies(company_ids) -> dict[int, CatalogPolicy]:
    """Политики пачки компаний одним запросом — для списков и сводок полноты (R1: без N+1)."""
    ids = {company_id for company_id in company_ids if company_id}
    if not ids:
        return {}
    from parties.models import CompanySettings

    rows = CompanySettings.objects.filter(company_id__in=ids).values_list(
        "company_id", "catalog_price_visibility", "catalog_publish_threshold"
    )
    return {
        company_id: CatalogPolicy(price_visibility=visibility, publish_threshold=threshold)
        for company_id, visibility, threshold in rows
    }


def policy_for(company_id) -> CatalogPolicy:
    """Политика одной компании; нет компании или строки настроек — умолчания."""
    return load_policies([company_id]).get(company_id, DEFAULT_POLICY) if company_id else DEFAULT_POLICY


def effective_price_visibility(product, policy: CatalogPolicy | None = None) -> str:
    """Видимость цены карточки: своя политика карточки, иначе политика компании-владельца."""
    if product.price_visibility:
        return product.price_visibility
    policy = policy if policy is not None else policy_for(product.owner_company_id)
    return policy.price_visibility

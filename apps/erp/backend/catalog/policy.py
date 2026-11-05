"""Политика каталога компании: видимость цен по умолчанию и порог публикации (M1-ERP-07).

Источник — `parties.CompanySettings` компании-владельца карточки (ARCHITECTURE §7: «ERP →
Настройки → политики каталога»). Чтение НЕ создаёт строку настроек: нет строки — действуют
умолчания продукта («по запросу», порог 100 %), как и у других настроек компании.

Видимость цены карточки — три уровня, сверху вниз (PART-3, решение владельца 2026-11-04): своя политика карточки →
договорённость с партнёром (`parties.CompanyRelationship.catalog_price_visibility` источника данных карточки,
`Product.source_supplier`) → политика компании. Цену-витрину задаёт сама карточка (`Product.list_price`), предложение
партнёра для витрины не выбирается, поэтому партнёр карточки — её источник данных.
"""

from __future__ import annotations

from dataclasses import dataclass

from .constants import DEFAULT_OFFER_CONFIRM_DAYS, DEFAULT_PUBLISH_THRESHOLD, PriceVisibility


@dataclass(frozen=True)
class CatalogPolicy:
    price_visibility: str = PriceVisibility.ON_REQUEST
    publish_threshold: int = DEFAULT_PUBLISH_THRESHOLD
    #: PART-2: через сколько дней без подтверждения цена поставщика «устарела» (`catalog/offer_freshness.py`).
    offer_confirm_days: int = DEFAULT_OFFER_CONFIRM_DAYS


DEFAULT_POLICY = CatalogPolicy()


def load_policies(company_ids) -> dict[int, CatalogPolicy]:
    """Политики пачки компаний одним запросом — для списков и сводок полноты (R1: без N+1)."""
    ids = {company_id for company_id in company_ids if company_id}
    if not ids:
        return {}
    from parties.models import CompanySettings

    rows = CompanySettings.objects.filter(company_id__in=ids).values_list(
        "company_id", "catalog_price_visibility", "catalog_publish_threshold", "offer_confirm_days"
    )
    return {
        company_id: CatalogPolicy(
            price_visibility=visibility, publish_threshold=threshold, offer_confirm_days=confirm_days
        )
        for company_id, visibility, threshold, confirm_days in rows
    }


def policy_for(company_id) -> CatalogPolicy:
    """Политика одной компании; нет компании или строки настроек — умолчания."""
    return load_policies([company_id]).get(company_id, DEFAULT_POLICY) if company_id else DEFAULT_POLICY


def load_partner_price_visibility(supplier_ids) -> dict[int, str]:
    """Договорённости о цене с партнёрами пачки одним запросом: `{компания: «cabinet»|«on_request»}`; «как у компании» не входит.

    Статус отношения не смотрится: договорённость о ценах товаров партнёра не исчезает от приостановки его входа в кабинет.
    """
    ids = {supplier_id for supplier_id in supplier_ids if supplier_id}
    if not ids:
        return {}
    from parties.models import CompanyRelationship, RelationshipRole

    rows = (
        CompanyRelationship.objects.filter(company_id__in=ids, role=RelationshipRole.PARTNER)
        .exclude(catalog_price_visibility="")
        .values_list("company_id", "catalog_price_visibility")
    )
    return dict(rows)


def price_visibility_source(
    product, policy: CatalogPolicy | None = None, partners: dict[int, str] | None = None
) -> tuple[str, str]:
    """`(видимость, уровень)`: уровень — `item` (политика карточки), `partner` (договорённость) или `company`.

    `partners` — карта пачки (`load_partner_price_visibility`); без неё договорённость читается одним запросом.
    """
    if product.price_visibility:
        return product.price_visibility, "item"
    supplier_id = getattr(product, "source_supplier_id", None)
    if supplier_id:
        if partners is None:
            partners = load_partner_price_visibility([supplier_id])
        if partners.get(supplier_id):
            return partners[supplier_id], "partner"
    policy = policy if policy is not None else policy_for(product.owner_company_id)
    return policy.price_visibility, "company"


def effective_price_visibility(
    product, policy: CatalogPolicy | None = None, partners: dict[int, str] | None = None
) -> str:
    """Видимость цены карточки: карточка → партнёр (источник данных) → компания-владелец."""
    return price_visibility_source(product, policy, partners)[0]

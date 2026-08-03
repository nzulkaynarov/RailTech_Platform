"""Публикация карточки товара ВЛАДЕЛЬЦЕМ при достигнутой полноте.

До волны A публиковать мог только платформенный оператор (`bulk_publish` под `IsPlatformAdmin`),
и продавец не мог выпустить в каталог даже собственную карточку. Эталон обратный: у Amazon
Business, Alibaba и Shopify публикует ВЛАДЕЛЕЦ товара, а площадка модерирует пост-фактум и по
сигналам — иначе каталог не наполняется никогда.

Роль «проверяющего» играет не человек, а детерминированный порог полноты (Akeneo): пока не
заполнено обязательное для домена, кнопка недоступна и интерфейс прямо говорит, чего не хватает.
"""

from __future__ import annotations

from django.db import transaction

from .completeness import completeness

#: Максимум карточек за один пакетный вызов — та же граница, что у платформенного bulk_publish.
MAX_BATCH = 500


def can_manage(user, product) -> bool:
    """Владелец карточки или платформенный оператор."""
    if getattr(user, "is_platform_admin", False) or getattr(user, "is_superuser", False):
        return True
    owner_id = getattr(product, "owner_company_id", None)
    if not owner_id:
        return False
    return user.memberships.filter(is_active=True, company_id=owner_id).exists()


@transaction.atomic
def publish_product(product, actor) -> tuple[object | None, str | None]:
    """Опубликовать одну карточку. Возвращает `(product, error_code)`."""
    from .models import ProductStatus

    if not can_manage(actor, product):
        return None, "PRODUCT_NOT_YOURS"
    report = completeness(product)
    if not report["is_publishable"]:
        # Код ошибки называет НЕДОСТАЮЩЕЕ — пользователь не должен гадать, как у волны E2
        # с обязательными блоками шаблона (`TEMPLATE_MISSING_REQUIRED_BLOCKS`).
        return None, "PRODUCT_INCOMPLETE:" + ",".join(item["code"] for item in report["missing"])
    published = ProductStatus.objects.filter(code="PUBLISHED").first()
    if published is None:
        return None, "PRODUCT_STATUS_MISSING"
    product.status = published
    product.save(update_fields=["status", "updated_at"])
    return product, None


def publish_many(product_ids, actor) -> dict:
    """Пакетная публикация: владелец прямо просил «массово или единично».

    Возвращает `{published: [...], skipped: [{id, error}]}` — частичный успех честнее отказа
    всей пачки: у Akeneo и Shopify пакетное действие тоже отчитывается построчно.
    """
    from .models import Product

    ids = list(dict.fromkeys(product_ids))[:MAX_BATCH]
    published: list[int] = []
    skipped: list[dict] = []
    for product in Product.objects.filter(pk__in=ids).select_related("status", "domain_type", "uom", "category"):
        _card, error = publish_product(product, actor)
        if error:
            skipped.append({"id": product.pk, "error": error})
        else:
            published.append(product.pk)
    return {"published": published, "skipped": skipped}

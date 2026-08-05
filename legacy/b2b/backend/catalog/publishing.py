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


def can_manage(user, product, *, permission: str = "catalog.manage") -> bool:
    """Право распоряжаться карточкой (N3: слой `catalog.*` действующий, не декоративный).

    Продавец: членство владельца + пермишен CompanyRole (`catalog.manage` для правок,
    `catalog.publish` для публикации; legacy-фолбэк без роли — в member_has_permission).
    Оператор: только суб-роль с `moderation.force_override` — SUPPORT «только просмотр»
    не публикует и не правит чужие карточки (ADR-0004). Superuser — DBA-эскалация.
    """
    if getattr(user, "is_superuser", False):
        return True
    if getattr(user, "is_platform_admin", False):
        from accounts.constants import OperatorPermission
        from accounts.services.permissions import operator_has_permission

        return operator_has_permission(user, OperatorPermission.MODERATION_FORCE_OVERRIDE)
    owner_id = getattr(product, "owner_company_id", None)
    if not owner_id:
        return False
    from accounts.services.permissions import member_has_permission

    return member_has_permission(user, owner_id, permission)


def _seller_kyc_verified(product, actor) -> bool:
    """Прошла ли верификацию компания-владелец карточки.

    Оператор и суперпользователь проверке не подлежат: они публикуют не от своего имени,
    а в порядке модерации (`moderation.force_override`), и собственной компании у них нет.
    """
    if getattr(actor, "is_superuser", False) or getattr(actor, "is_platform_admin", False):
        return True
    owner_id = getattr(product, "owner_company_id", None)
    if not owner_id:
        return False
    from accounts.services.kyc import company_kyc_verified

    return company_kyc_verified(owner_id)


@transaction.atomic
def publish_product(product, actor) -> tuple[object | None, str | None]:
    """Опубликовать одну карточку. Возвращает `(product, error_code)`."""
    from .models import ProductStatus

    # Публикация — отдельная способность (`catalog.publish`): наполнять карточку может
    # менеджер каталога, а выпускать в общий каталог — тот, кому это доверено.
    if not can_manage(actor, product, permission="catalog.publish"):
        return None, "PRODUCT_NOT_YOURS"
    # Верификация компании нужна, чтобы карточка стала ВИДНА рынку, но не чтобы её завести.
    # Эталон Amazon Seller Central: листинги готовятся, пока идёт проверка аккаунта, а живыми
    # становятся после неё. Гейт не новый — он переехал СЮДА из навигации, где прятал раздел
    # целиком: до этой волны непроверенный продавец не мог ни наполнять каталог, ни грузить
    # прайс. Прав стало строго больше, публикация осталась там же, где была.
    if not _seller_kyc_verified(product, actor):
        return None, "SELLER_KYC_REQUIRED"
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

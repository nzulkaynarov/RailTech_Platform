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
    Администратор (`is_superuser`) — всегда.
    """
    if getattr(user, "is_superuser", False):
        return True
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
    if getattr(actor, "is_superuser", False) or getattr(actor, "is_superuser", False):
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


@transaction.atomic
def unpublish_product(product, actor) -> tuple[object | None, str | None]:
    """Снять карточку с витрины: PUBLISHED → DRAFT. Возвращает `(product, error_code)`.

    R2 (аудит §D10): до этой волны публикация была улицей с односторонним движением —
    выпустить карточку продавец мог, а убрать (ошибка в цене, товар закончился навсегда,
    юридическая претензия) — нет. Эталон Shopify: Active → Draft двусторонне.

    Право то же, что у публикации (`catalog.publish`): кто выпускает на витрину, тот и
    снимает. KYC-гейта здесь НЕТ намеренно: верификация нужна, чтобы карточка стала ВИДНА
    рынку, а снятие с витрины ЭКСПОЗИЦИЮ УМЕНЬШАЕТ — непроверенная компания обязана мочь
    убрать своё (наполнение до KYC открыто той же логикой, #550). Закреплено тестом.
    """
    from .models import ProductStatus

    if not can_manage(actor, product, permission="catalog.publish"):
        return None, "PRODUCT_NOT_YOURS"
    if getattr(product.status, "code", None) != "PUBLISHED":
        return None, "PRODUCT_NOT_PUBLISHED"
    draft = ProductStatus.objects.filter(code="DRAFT").first()
    if draft is None:
        return None, "PRODUCT_STATUS_MISSING"
    product.status = draft
    product.save(update_fields=["status", "updated_at"])
    return product, None


@transaction.atomic
def archive_product(product, actor) -> tuple[object | None, str | None]:
    """Убрать карточку в архив (любой статус → ARCHIVED). Возвращает `(product, error_code)`.

    Архив отделён от снятия с публикации (Shopify: Archive — отдельное, ОБРАТИМОЕ действие):
    Draft — «ещё готовится», Archive — «больше не работаем». Право — `catalog.manage`
    (распоряжение составом каталога, не витриной). KYC-гейта нет намеренно — архив
    уменьшает экспозицию, см. unpublish_product.
    """
    from .models import ProductStatus

    if not can_manage(actor, product, permission="catalog.manage"):
        return None, "PRODUCT_NOT_YOURS"
    if getattr(product.status, "code", None) == "ARCHIVED":
        return None, "PRODUCT_ALREADY_ARCHIVED"
    archived = ProductStatus.objects.filter(code="ARCHIVED").first()
    if archived is None:
        return None, "PRODUCT_STATUS_MISSING"
    product.status = archived
    product.save(update_fields=["status", "updated_at"])
    return product, None


@transaction.atomic
def restore_product(product, actor) -> tuple[object | None, str | None]:
    """Вернуть карточку из архива в черновики: ARCHIVED → DRAFT.

    Закрывает «архив — чёрную дыру» (аудит §D15): слитый дубль уходил в ARCHIVED и исчезал
    из всех вкладок без пути назад. Возврат — в DRAFT, а не сразу в PUBLISHED: витрину
    карточка должна заслужить заново через publish (полнота + KYC), как у Shopify
    unarchive → Draft.
    """
    from .models import ProductStatus

    if not can_manage(actor, product, permission="catalog.manage"):
        return None, "PRODUCT_NOT_YOURS"
    if getattr(product.status, "code", None) != "ARCHIVED":
        return None, "PRODUCT_NOT_ARCHIVED"
    draft = ProductStatus.objects.filter(code="DRAFT").first()
    if draft is None:
        return None, "PRODUCT_STATUS_MISSING"
    product.status = draft
    product.save(update_fields=["status", "updated_at"])
    return product, None


def archive_many(product_ids, actor) -> dict:
    """Пакетный архив с ПОСТРОЧНЫМ отчётом `{archived: [...], skipped: [{product_id, error}]}`.

    Тот же контракт частичного успеха, что у publish_many: смесь своих и чужих карточек не
    валит всю пачку — чужие честно перечисляются в skipped.
    """
    from .models import Product

    ids = list(dict.fromkeys(product_ids))[:MAX_BATCH]
    archived: list[int] = []
    skipped: list[dict] = []
    for product in Product.objects.filter(pk__in=ids).select_related("status"):
        _card, error = archive_product(product, actor)
        if error:
            skipped.append({"product_id": product.pk, "error": error})
        else:
            archived.append(product.pk)
    return {"archived": archived, "skipped": skipped}


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

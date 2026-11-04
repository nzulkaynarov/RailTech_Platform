"""Фото товара в карточке (CAT-CARD-1): до 10 штук, ровно одно главное, порядок задаёт сотрудник.

Правила (решение архитектора 2026-11-03, эталоны Odoo 17 `product.image`, GS1 Product Image Specification):
- до `MAX_IMAGES` фото на товар; JPEG, PNG или WebP до 5 МБ, SVG и GIF не принимаются (SVG несёт скрипты — аудит H6);
- первое загруженное фото становится главным само; при удалении главного главным становится следующее по порядку;
- порядок — позиции 0..n-1 без дыр: любая операция пересчитывает их, поэтому «переставить» — это «поставить на позицию»;
- подсказка «квадрат, от 900 px, светлый фон» живёт в интерфейсе и ничего не блокирует.
Все операции берут строку товара под `select_for_update`, поэтому две одновременные загрузки не пробьют лимит и не оставят
двух главных. Файл лежит в публичном бакете (`/media/products/<id>/images/…`); в Платформу он идёт только через BFF.
"""

import logging
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
from django.db import transaction

from catalog.desk.items import ItemError
from catalog.models import Product, ProductImage
from core.validators import IMAGE_MAX_SIZE, _validate_file

logger = logging.getLogger(__name__)

MAX_IMAGES = 10
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALT_MAX = 255


def validate_image(file) -> None:
    """Расширение, тип, подпись файла и размер; отказ — `ItemError` с кодом ответа."""
    try:
        _validate_file(file, IMAGE_EXTENSIONS, IMAGE_CONTENT_TYPES, IMAGE_MAX_SIZE, label="Image")
    except ValidationError as error:
        message = " ".join(error.messages)
        if "exceeds" in message:
            raise ItemError("FILE_TOO_LARGE", "image") from None
        if "does not match" in message:
            raise ItemError("FILE_CONTENT_MISMATCH", "image") from None
        raise ItemError("FILE_TYPE_NOT_ALLOWED", "image") from None


def media_path(image: ProductImage) -> str:
    """Путь `/media/...` файла: BFF запрашивает его у ERP сам (браузер к ERP не ходит)."""
    if not image.image:
        return ""
    return urlparse(image.image.url).path


def image_row(image: ProductImage) -> dict:
    return {
        "id": image.pk,
        "url": media_path(image),
        "is_main": image.is_main,
        "sort_order": image.sort_order,
        "alt": image.alt_text,
    }


def ordered(product: Product) -> list[ProductImage]:
    return list(ProductImage.objects.filter(product=product).order_by("sort_order", "id"))


def _lock(product: Product) -> None:
    Product.objects.select_for_update().filter(pk=product.pk).first()


def _renumber(images: list[ProductImage], stored: dict[int, tuple[int, bool]]) -> None:
    """Позиции 0..n-1 и ровно одно главное (если фото есть); пишется только то, что отличается от `stored` (id -> позиция, главное)."""
    if images and not any(image.is_main for image in images):
        images[0].is_main = True
    seen_main = False
    for position, image in enumerate(images):
        image.is_main = image.is_main and not seen_main
        seen_main = seen_main or image.is_main
        image.sort_order = position
        if stored.get(image.pk) != (position, image.is_main):
            image.save(update_fields=["sort_order", "is_main"])


def _stored(images: list[ProductImage]) -> dict[int, tuple[int, bool]]:
    return {image.pk: (image.sort_order, image.is_main) for image in images}


@transaction.atomic
def add_image(product: Product, file, *, alt: str = "", make_main: bool = False) -> ProductImage:
    """Новое фото в конец списка. Первое — главное; `make_main` ставит главным и не первое."""
    validate_image(file)
    _lock(product)
    images = ordered(product)
    if len(images) >= MAX_IMAGES:
        raise ItemError("IMAGE_LIMIT_REACHED", "image")
    if make_main:
        ProductImage.objects.filter(product=product, is_main=True).update(is_main=False)
    return ProductImage.objects.create(
        product=product,
        image=file,
        alt_text=(alt or "").strip()[:ALT_MAX],
        is_main=make_main or not images,
        sort_order=len(images),
    )


def get_image(product: Product, image_id) -> ProductImage:
    image = ProductImage.objects.filter(product=product, pk=image_id).first() if str(image_id).isdigit() else None
    if image is None:
        raise ItemError("IMAGE_NOT_FOUND", "image_id")
    return image


@transaction.atomic
def update_image(product: Product, image_id, data: dict) -> ProductImage:
    """`is_main` (только `true`: главное меняется назначением нового), `sort_order` (позиция с 0), `alt_text`."""
    _lock(product)
    target = get_image(product, image_id)
    images = ordered(product)
    stored = _stored(images)
    target = next(image for image in images if image.pk == target.pk)
    if "alt_text" in data:
        target.alt_text = (data["alt_text"] or "").strip()[:ALT_MAX]
        target.save(update_fields=["alt_text"])
    if "is_main" in data and data["is_main"] is not None:
        if data["is_main"]:
            for image in images:
                image.is_main = image.pk == target.pk
        elif target.is_main:
            raise ItemError("IMAGE_MAIN_REQUIRED", "is_main")
    if data.get("sort_order") is not None:
        position = data["sort_order"]
        if not isinstance(position, int) or isinstance(position, bool) or position < 0:
            raise ItemError("IMAGE_ORDER_INVALID", "sort_order")
        images.remove(target)
        images.insert(min(position, len(images)), target)
    _renumber(images, stored)
    return get_image(product, target.pk)


@transaction.atomic
def delete_image(product: Product, image_id) -> None:
    """Удаляет запись и файл; если было главное — главным становится следующее по порядку."""
    _lock(product)
    target = get_image(product, image_id)
    name, storage = (target.image.name, target.image.storage) if target.image else ("", None)
    target.delete()
    rest = ordered(product)
    _renumber(rest, _stored(rest))
    if name:
        try:
            storage.delete(name)
        except Exception:  # noqa: BLE001 — запись уже удалена; осиротевший объект хранилища не должен давать 500
            logger.exception("фото товара %s: файл %s не удалён из хранилища", product.pk, name)

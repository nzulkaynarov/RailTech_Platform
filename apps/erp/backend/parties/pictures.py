"""Логотип компании и фото контакта (ЕД-5, СУЩ-3): проверка, перекодирование, версия и размеры для строк.

Правила (образец — аватар сотрудника CRM и миниатюра позиции каталога):
- JPEG, PNG или WebP до `MAX_BYTES`; расширение, заявленный тип и подпись файла должны совпасть, SVG и GIF не принимаются;
- файл перекодируется в квадрат `SIDE`×`SIDE` WebP: метаданные и всё лишнее внутри файла не хранятся;
- адреса хранилища наружу не отдаются никогда: клиент получает только `version` и берёт картинку у ERP через Платформу;
- `version` — короткий отпечаток имени файла: новая загрузка даёт новое имя, значит и новую версию (адрес `?v=` сбрасывает кэш).
"""

import hashlib
import logging
from io import BytesIO

from django.core.files.base import ContentFile

from catalog.desk.items import ItemError
from core.validators import AVATAR_MAX_SIZE, _validate_file

logger = logging.getLogger(__name__)

SIDE = 256
ROW_SIDE = 96
MAX_BYTES = AVATAR_MAX_SIZE
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
SIZES = {"row": ROW_SIDE, "full": SIDE}
CACHE_SECONDS = 7 * 24 * 3600


def normalize(file) -> bytes:
    """Проверяет файл и отдаёт квадратный WebP `SIDE`×`SIDE`; отказ — `ItemError` с кодом и полем `file`."""
    from django.core.exceptions import ValidationError
    from PIL import Image, ImageOps

    try:
        _validate_file(file, EXTENSIONS, CONTENT_TYPES, MAX_BYTES, label="Image")
    except ValidationError as error:
        message = " ".join(error.messages)
        if "exceeds" in message:
            raise ItemError("FILE_TOO_LARGE", "file") from None
        if "does not match" in message:
            raise ItemError("FILE_CONTENT_MISMATCH", "file") from None
        raise ItemError("FILE_TYPE_NOT_ALLOWED", "file") from None
    try:
        file.seek(0)
        with Image.open(file) as source:
            picture = ImageOps.exif_transpose(source)
            picture = picture.convert("RGBA" if "A" in picture.getbands() or "transparency" in picture.info else "RGB")
            picture = ImageOps.fit(picture, (SIDE, SIDE), method=Image.Resampling.LANCZOS)
    except Exception:  # noqa: BLE001 — любой сбой разбора: это не картинка, а подделка под неё
        raise ItemError("FILE_CONTENT_MISMATCH", "file") from None
    out = BytesIO()
    picture.save(out, format="WEBP", quality=85, method=4)
    return out.getvalue()


def version(field) -> str | None:
    """Отпечаток имени файла: `None`, пока картинки нет."""
    name = getattr(field, "name", "") or ""
    return hashlib.sha1(name.encode("utf-8")).hexdigest()[:10] if name else None


def replace(instance, attr: str, file, *, extra_fields: tuple[str, ...] = ("updated_at",)) -> None:
    """Кладёт новую картинку в поле `attr` и удаляет прежнюю из хранилища (после записи в базу)."""
    data = normalize(file)
    field = getattr(instance, attr)
    old_name, storage = (field.name, field.storage) if field else ("", None)
    field.save(f"{attr}.webp", ContentFile(data), save=False)
    instance.save(update_fields=[attr, *extra_fields])
    _drop(storage, old_name)


def remove(instance, attr: str, *, extra_fields: tuple[str, ...] = ("updated_at",)) -> None:
    field = getattr(instance, attr)
    if not field:
        return
    name, storage = field.name, field.storage
    setattr(instance, attr, None)
    instance.save(update_fields=[attr, *extra_fields])
    _drop(storage, name)


def _drop(storage, name: str) -> None:
    if not name:
        return
    try:
        storage.delete(name)
    except Exception:  # noqa: BLE001 — запись уже обновлена; осиротевший объект не должен давать 500
        logger.exception("картинка %s не удалена из хранилища", name)


def render(field, size: str = "row") -> bytes:
    """WebP нужной стороны (`row` 96 px для строк, `full` 256 px для шапки карточки); `OSError` — файла нет в хранилище."""
    from django.core.cache import cache
    from PIL import Image

    side = SIZES.get(size, ROW_SIDE)
    key = f"parties:picture:v1:{side}:{field.name}"  # новое имя файла — новый ключ, старый просто истекает
    cached = cache.get(key)
    if cached is not None:
        return cached
    with field.open("rb") as handle, Image.open(handle) as source:
        picture = source.convert("RGBA")
        if side != picture.width:
            picture = picture.resize((side, side), Image.Resampling.LANCZOS)
    out = BytesIO()
    picture.save(out, format="WEBP", quality=85, method=4)
    data = out.getvalue()
    cache.set(key, data, CACHE_SECONDS)
    return data

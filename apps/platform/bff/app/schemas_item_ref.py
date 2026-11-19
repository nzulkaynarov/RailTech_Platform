"""Позиция каталога в строке любого документа (план ЕД-4, `ui-standard.md` §12).

Одна схема на все экраны. ERP отдаёт `{id, name, sku, kind, photo}` (`catalog.item_ref`); BFF
превращает id фото в адрес своей миниатюры с версией — новое главное фото даёт новый адрес, и
браузер не показывает старое из кэша.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

THUMBNAIL_PATH = "/api/v1/erp/catalog/items/{id}/thumbnail"


class ItemRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    #: Наш артикул; пусто — у карточки его ещё нет
    sku: str
    kind: Literal["goods", "service"]
    #: Миниатюра главного фото; `None` — фото нет, интерфейс показывает значок типа
    thumbnail: str | None


def _int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def thumbnail_url(product_id: Any, photo: Any) -> str | None:
    pid, image = _int(product_id), _int(photo)
    if pid is None or image is None:
        return None
    return f"{THUMBNAIL_PATH.format(id=pid)}?v={image}"


def item_ref(raw: Any) -> ItemRef | None:
    """Ссылка из ответа ERP; нет или битая — `None` (строка без карточки показывается текстом)."""
    if not isinstance(raw, dict):
        return None
    pid, name = _int(raw.get("id")), raw.get("name")
    if pid is None or not isinstance(name, str) or not name:
        return None
    sku = raw.get("sku")
    return ItemRef(
        id=str(pid),
        name=name,
        sku=sku if isinstance(sku, str) else "",
        kind="service" if raw.get("kind") == "service" else "goods",
        thumbnail=thumbnail_url(pid, raw.get("photo")),
    )

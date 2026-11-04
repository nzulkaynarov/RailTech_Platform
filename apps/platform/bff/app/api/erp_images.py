"""Номенклатура · Фото позиции (контракт BFF, тег `erp-catalog`; CAT-CARD-1).

BFF проксирует к ERP `catalog/items/{id}/images/` с токеном сотрудника (раздел `erp.stock`:
чтение — `read`, загрузка, правка и удаление — `full`; право `catalog.manage` решает ERP).
Загрузка: тело читается до предела (5 МБ + поля формы) и передаётся ERP как есть; тип файла,
подпись и число фото проверяет ERP. Файл в браузер отдаёт только BFF (`…/content`): CSP
Платформы `img-src 'self' data: blob:` не пускает адреса хранилища ERP, а BFF берёт файл по
пути из карточки этой позиции."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response, status

from app.api.erp_catalog import _erp
from app.deps import Authed, require
from app.errors import PlatformError
from app.schemas_erp_catalog import ItemImage, ItemImageUpdate, to_image

router = APIRouter(tags=["erp-catalog"])

Reader = Annotated[Authed, Depends(require("erp.stock", "read"))]
Writer = Annotated[Authed, Depends(require("erp.stock", "full"))]
Id = Annotated[str, Path(pattern=r"^[0-9]+$")]

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_BODY_BYTES = MAX_IMAGE_BYTES + 256 * 1024  # поля формы и границы multipart


def _too_large() -> PlatformError:
    return PlatformError(
        "PAYLOAD_TOO_LARGE",
        "Фото больше 5 МБ.",
        status_code=413,
        details={"max_bytes": MAX_IMAGE_BYTES},
    )


async def _read_limited(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise _too_large()
    return bytes(body)


def _image_field(error: PlatformError) -> PlatformError:
    """Отказ по файлу ERP называет поле `file`; у фото оно `image`."""
    details = error.body.details
    if details and details.get("fields") == ["file"]:
        details["fields"] = ["image"]
    return error


@router.post(
    "/erp/catalog/items/{id}/images",
    response_model=ItemImage,
    status_code=status.HTTP_201_CREATED,
    operation_id="uploadCatalogItemImage",
)
async def upload_image(id: Id, request: Request, authed: Writer) -> ItemImage:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Фото нужно передать формой multipart.",
            status_code=422,
            details={"fields": ["image"], "reason": "multipart_required"},
        )
    body = await _read_limited(request)
    try:
        response = await _erp(authed).request(
            "POST", f"catalog/items/{id}/images/", content=body, content_type=content_type
        )
    except PlatformError as error:
        raise _image_field(error) from error
    return to_image(response.json())


@router.patch(
    "/erp/catalog/items/{id}/images/{image_id}",
    response_model=ItemImage,
    operation_id="updateCatalogItemImage",
)
async def update_image(id: Id, image_id: Id, body: ItemImageUpdate, authed: Writer) -> ItemImage:
    data = await _erp(authed).data(
        "PATCH", f"catalog/items/{id}/images/{image_id}/", json=body.sent()
    )
    return to_image(data)


@router.delete(
    "/erp/catalog/items/{id}/images/{image_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteCatalogItemImage",
)
async def delete_image(id: Id, image_id: Id, authed: Writer) -> Response:
    await _erp(authed).request("DELETE", f"catalog/items/{id}/images/{image_id}/")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/erp/catalog/items/{id}/images/{image_id}/content",
    response_class=Response,
    responses={200: {"content": {"image/*": {}}}},
    operation_id="getCatalogItemImageContent",
)
async def image_content(id: Id, image_id: Id, authed: Reader) -> Response:
    erp = _erp(authed)
    card = await erp.data("GET", f"catalog/items/{id}/")
    url = next(
        (
            i.get("url")
            for i in card.get("images") or []
            if isinstance(i, dict) and str(i.get("id")) == image_id
        ),
        None,
    )
    file = await erp.media(url, product_id=id)
    if file is None:
        raise PlatformError("NOT_FOUND", "Фото нет.", status_code=404)
    return Response(
        content=file.content,
        media_type=file.headers["content-type"].split(";")[0].strip(),
        headers={
            "Cache-Control": "private, max-age=300",
            "Content-Disposition": "inline",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )

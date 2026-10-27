"""Чтение загрузки фото профиля с отсечкой по размеру (W15-H6).

Тело читается потоком и обрывается на пределе (1 МБ файла + запас на границы multipart):
разбор формы Starlette иначе принимает тело любого размера на диск до вызова обработчика.
"""

from collections.abc import AsyncGenerator

from fastapi import Request, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from app.domain.errors import PayloadTooLargeError, Reason, ValidationFailedError
from app.domain.staff_profile import AVATAR_MAX_BYTES

MULTIPART_OVERHEAD = 64 * 1024
BODY_LIMIT = AVATAR_MAX_BYTES + MULTIPART_OVERHEAD


def _too_large() -> PayloadTooLargeError:
    return PayloadTooLargeError(
        "avatar is larger than 1 MB",
        reason=Reason.AVATAR_TOO_LARGE,
        field="avatar",
        max_bytes=AVATAR_MAX_BYTES,
    )


async def _capped(request: Request) -> AsyncGenerator[bytes, None]:
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > BODY_LIMIT:
            raise _too_large()
        yield chunk


async def read_avatar(request: Request) -> tuple[bytes, str | None]:
    """Файл из поля `avatar` и тип, который назвал клиент; больше предела — 413."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > BODY_LIMIT:
        raise _too_large()
    try:
        form = await MultiPartParser(
            request.headers, _capped(request), max_files=1, max_fields=1
        ).parse()
    except MultiPartException as exc:
        raise ValidationFailedError(
            "multipart/form-data with the field avatar is required",
            reason=Reason.AVATAR_UNSUPPORTED_TYPE,
            field="avatar",
        ) from exc
    file = form.get("avatar")
    if not isinstance(file, UploadFile):
        raise ValidationFailedError(
            "the field avatar is required", reason=Reason.AVATAR_EMPTY, field="avatar"
        )
    data = await file.read(AVATAR_MAX_BYTES + 1)
    await file.close()
    return data, file.content_type

"""Профиль сотрудника: страница /me — поля, фото, Telegram сам, замещение (tag `me`, 0.21.0).

Доступно каждому вошедшему и только про себя: решения и данные — в CRM (ADR-0015), токеном самого
сотрудника; BFF переводит поля и ошибки в формат `Error` и отдаёт фото без публичных ссылок на S3.
"""

import re
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Path, Request, Response, status

from app.deps import AuthedDep
from app.errors import PlatformError, backend_reason, from_backend
from app.schemas import Me, build_me
from app.schemas_profile import (
    Colleague,
    DeputyUpdate,
    Profile,
    ProfileUpdate,
    TelegramLink,
    to_profile,
)

router = APIRouter(tags=["me"])

ME = "/api/v1/me"
MAX_AVATAR_BYTES = 1024 * 1024
_MULTIPART_OVERHEAD = 64 * 1024  # границы и заголовки частей поверх файла
AVATAR_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})
_AVATAR_PART = re.compile(
    rb'content-disposition:[^\r\n]*name="avatar"[^\r\n]*\r\n'
    rb"(?:[^\r\n]+\r\n)*?content-type:[ \t]*([^\r\n;]+)",
    re.IGNORECASE,
)
_PART_HEADERS_WINDOW = 4096
_MESSAGES = {
    "phone_invalid": "Телефон: от 7 до 15 цифр, можно с «+».",
    "timezone_unknown": "Такого часового пояса нет.",
    "signature_invalid": "Подпись: не длиннее 1000 символов.",
    "avatar_empty": "Файл пустой.",
    "avatar_too_large": "Фото больше 1 МБ.",
    "avatar_unsupported_type": "Нужна картинка PNG, JPEG или WebP.",
    "avatar_type_mismatch": "Тип файла не совпадает с содержимым.",
    "deputy_is_self": "Заместителем нельзя назначить себя.",
    "deputy_period_reversed": "Дата окончания раньше даты начала.",
    "deputy_period_past": "Период уже закончился.",
    "deputy_period_too_long": "Период не может быть дольше года.",
    "deputy_not_colleague": "Этот сотрудник не может вести очередь.",
}
BOT_MISSING = (
    "Бот не подключён: попросите администратора подключить Telegram-бота в «Подключениях»."
)
BOT_STOPPED = "Бот сейчас не запущен. Попробуйте через минуту или напишите администратору."


def _json(response: httpx.Response) -> Any:
    if response.status_code >= 400:
        raise _translate(response)
    return response.json()


def _translate(response: httpx.Response) -> PlatformError:
    """4xx CRM -> `Error`: ошибка значения несёт `details.fields` и `details.reason`."""
    reason = backend_reason(response)
    if response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT and reason in _MESSAGES:
        field = _field_of(response)
        return PlatformError(
            "VALIDATION_FAILED",
            _MESSAGES[reason],
            status_code=422,
            source="crm",
            details={"fields": [field] if field else [], "reason": reason},
        )
    if response.status_code == status.HTTP_413_CONTENT_TOO_LARGE:
        return _too_large()
    if response.status_code == status.HTTP_409_CONFLICT and reason == "bot_not_configured":
        return PlatformError(
            "NOT_CONFIGURED",
            BOT_MISSING,
            status_code=409,
            source="crm",
            details={"reason": reason},
        )
    if response.status_code == status.HTTP_409_CONFLICT and reason == "bot_not_running":
        return PlatformError(
            "CONFLICT", BOT_STOPPED, status_code=409, source="crm", details={"reason": reason}
        )
    err = from_backend("crm", response)
    if reason and err.body.details is not None:
        err.body.details["reason"] = reason
    return err


def _field_of(response: httpx.Response) -> str | None:
    try:
        field = response.json()["details"]["field"]
    except (ValueError, KeyError, TypeError):
        return None
    if field == "deputy_user_id":
        return "deputy_id"
    if field == "full_name":
        return "name"
    return field if isinstance(field, str) else None


async def _covering(authed: AuthedDep) -> list[dict[str, Any]]:
    response = await authed.call("crm", "GET", f"{ME}/covering")
    if response.status_code != 200:
        return []  # замещение — подсказка в профиле; профиль без неё лучше, чем ошибка
    body = response.json()
    return [row for row in body if isinstance(row, dict)] if isinstance(body, list) else []


async def _profile_of(authed: AuthedDep, crm_me: dict[str, Any]) -> Profile:
    await authed.service.apply_profile(authed.sid, crm_me)
    return to_profile(crm_me, await _covering(authed))


@router.get(
    "/me/profile",
    response_model=Profile,
    response_model_exclude_none=True,
    operation_id="getProfile",
)
async def get_profile(authed: AuthedDep) -> Profile:
    return await _profile_of(authed, _json(await authed.call("crm", "GET", ME)))


@router.patch(
    "/me/profile",
    response_model=Profile,
    response_model_exclude_none=True,
    operation_id="updateProfile",
)
async def update_profile(body: ProfileUpdate, authed: AuthedDep) -> Profile:
    crm_me = _json(await authed.call("crm", "PATCH", ME, json=body.to_crm()))
    return await _profile_of(authed, crm_me)


async def _avatar_body(request: Request) -> tuple[bytes, str]:
    """Тело загрузки потоком: на пределе чтение обрывается (413), в памяти — не больше предела."""
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise _bad_avatar("avatar_unsupported_type")
    limit = MAX_AVATAR_BYTES + _MULTIPART_OVERHEAD
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            raise _too_large()
    # Тип части `avatar` — из её заголовков (начало тела); содержимое проверяет CRM.
    found = _AVATAR_PART.search(bytes(body[:_PART_HEADERS_WINDOW]))
    mime = found.group(1).strip().lower().decode("ascii", "ignore") if found else ""
    if mime not in AVATAR_TYPES:
        raise _bad_avatar("avatar_unsupported_type")
    return bytes(body), content_type


def _too_large() -> PlatformError:
    return PlatformError(
        "PAYLOAD_TOO_LARGE",
        _MESSAGES["avatar_too_large"],
        status_code=413,
        details={"fields": ["avatar"], "reason": "avatar_too_large", "max_bytes": MAX_AVATAR_BYTES},
    )


def _bad_avatar(reason: str) -> PlatformError:
    return PlatformError(
        "VALIDATION_FAILED",
        _MESSAGES[reason],
        status_code=422,
        details={"fields": ["avatar"], "reason": reason},
    )


@router.put("/me/avatar", response_model=Me, operation_id="uploadAvatar")
async def upload_avatar(request: Request, authed: AuthedDep) -> Me:
    content, content_type = await _avatar_body(request)
    response = await authed.call(
        "crm", "PUT", f"{ME}/avatar", content=content, content_type=content_type
    )
    return build_me(await authed.service.apply_profile(authed.sid, _json(response)))


@router.delete("/me/avatar", response_model=Me, operation_id="deleteAvatar")
async def delete_avatar(authed: AuthedDep) -> Me:
    response = await authed.call("crm", "DELETE", f"{ME}/avatar")
    return build_me(await authed.service.apply_profile(authed.sid, _json(response)))


@router.get(
    "/staff/{id}/avatar",
    response_class=Response,
    operation_id="getStaffAvatar",
    responses={200: {"content": {"image/*": {}}}},
)
async def get_staff_avatar(
    authed: AuthedDep, user_id: Annotated[str, Path(alias="id", pattern=r"^[1-9][0-9]*$")]
) -> Response:
    """Фото коллеги потоком через BFF: ссылок на хранилище наружу нет."""
    response = await authed.call("crm", "GET", f"/api/v1/staff/{user_id}/avatar")
    if response.status_code == status.HTTP_404_NOT_FOUND:
        raise PlatformError("NOT_FOUND", "Фото нет.", status_code=404)
    if response.status_code != status.HTTP_200_OK:
        raise from_backend("crm", response)
    mime = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if mime not in AVATAR_TYPES:
        raise PlatformError("NOT_FOUND", "Фото нет.", status_code=404)
    return Response(
        content=response.content,
        media_type=mime,
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": "inline",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.post("/me/telegram-link", response_model=TelegramLink, operation_id="createTelegramLink")
async def create_telegram_link(authed: AuthedDep) -> TelegramLink:
    body = _json(await authed.call("crm", "POST", f"{ME}/telegram-link"))
    return TelegramLink(url=str(body["url"]), expires_at=str(body["expires_at"]))


@router.delete(
    "/me/telegram-link",
    response_model=Profile,
    response_model_exclude_none=True,
    operation_id="deleteTelegramLink",
)
async def delete_telegram_link(authed: AuthedDep) -> Profile:
    return await _profile_of(
        authed, _json(await authed.call("crm", "DELETE", f"{ME}/telegram-link"))
    )


@router.get(
    "/me/deputy-candidates",
    response_model=list[Colleague],
    response_model_exclude_none=True,
    operation_id="listDeputyCandidates",
)
async def list_deputy_candidates(authed: AuthedDep) -> list[Colleague]:
    rows = _json(await authed.call("crm", "GET", f"{ME}/deputy-candidates"))
    return [
        Colleague(id=str(r["id"]), name=str(r["full_name"]), position=r.get("position") or None)
        for r in rows
    ]


@router.put(
    "/me/deputy",
    response_model=Profile,
    response_model_exclude_none=True,
    operation_id="setDeputy",
)
async def set_deputy(body: DeputyUpdate, authed: AuthedDep) -> Profile:
    payload = {
        "deputy_user_id": int(body.deputy_id),
        "date_from": body.date_from,
        "date_to": body.date_to,
    }
    return await _profile_of(
        authed, _json(await authed.call("crm", "PUT", f"{ME}/deputy", json=payload))
    )


@router.delete(
    "/me/deputy",
    response_model=Profile,
    response_model_exclude_none=True,
    operation_id="clearDeputy",
)
async def clear_deputy(authed: AuthedDep) -> Profile:
    return await _profile_of(authed, _json(await authed.call("crm", "DELETE", f"{ME}/deputy")))

"""Логотип контрагента и фото его контакта (ЕД-5, СУЩ-3; контракт BFF, тег `chats`).

Файл хранит и проверяет ERP (`parties/organizations/{id}/logo/`, `parties/people/{id}/photo/`):
тип, подпись и размер, перекодирование в квадрат WebP. BFF проверяет раздел каталога, читает тело
потоком до предела и передаёт его как есть; правит тот, кто правит реквизиты (ERP — `deal.manage`
или `supply.manage`). Картинки в браузер отдаёт только BFF с версией в адресе (`?v=`): адресов
хранилища наружу нет.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from pydantic import BaseModel, ConfigDict

from app.api.people_contacts import CounterpartyCard, RequisitesWriter, to_card
from app.clients.erp_company import ErpCompany
from app.deps import Authed, Rule, require_any
from app.errors import PlatformError
from app.schemas_pictures import company_logo_url, contact_photo_url

router = APIRouter(tags=["chats"])

CompanyId = Annotated[str, Path(pattern=r"^[0-9]+$")]
ContactId = Annotated[str, Path(pattern=r"^[0-9]+$")]
Size = Annotated[str | None, Query(pattern=r"^(row|full)$")]
# Логотип видят там, где видна карточка контрагента; фото — ещё и в списке «Люди»
LOGO_SECTIONS: tuple[Rule, ...] = (
    ("crm.clients", "read"),
    ("erp.stock", "read"),
    ("eds.projects", "read"),
    ("eds.payments", "read"),
    ("eds.inbox", "read"),
)
LogoReader = Annotated[Authed, Depends(require_any(*LOGO_SECTIONS))]
PhotoReader = Annotated[
    Authed,
    Depends(
        require_any(("chats.internal", "read"), ("crm.clients", "read"), ("erp.stock", "read"))
    ),
]

LOGO_BATCH = 100
MAX_PICTURE_BYTES = 2 * 1024 * 1024
MAX_BODY_BYTES = MAX_PICTURE_BYTES + 256 * 1024  # поля формы и границы multipart
_NO_PICTURE = "Картинки нет."


class ContactPhoto(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    photo_url: str | None


def _too_large() -> PlatformError:
    return PlatformError(
        "PAYLOAD_TOO_LARGE",
        "Картинка больше 2 МБ.",
        status_code=413,
        details={"max_bytes": MAX_PICTURE_BYTES},
    )


async def _multipart(request: Request) -> tuple[bytes, str]:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Картинку нужно передать формой multipart.",
            status_code=422,
            details={"fields": ["file"], "reason": "multipart_required"},
        )
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        raise _too_large()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY_BYTES:
            raise _too_large()
    return bytes(body), content_type


def _image(response: Any) -> Response:
    if response.headers.get("content-type", "").split(";")[0].strip().lower() != "image/webp":
        raise PlatformError("NOT_FOUND", _NO_PICTURE, status_code=404)
    return Response(
        content=response.content,
        media_type="image/webp",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@router.get(
    "/people/counterparties/{id}/logo",
    response_class=Response,
    responses={200: {"content": {"image/webp": {}}}},
    operation_id="getCounterpartyLogo",
)
async def get_logo(
    id: CompanyId, authed: LogoReader, size: Size = None, v: str | None = None
) -> Response:
    """Логотип WebP; `?v=<версия>` неизменен, пока логотип тот же: кэш браузера на сутки."""
    params = {"size": size} if size else None
    return _image(
        await ErpCompany(authed.call).request(
            "GET", f"parties/organizations/{id}/logo/", params=params
        )
    )


@router.put(
    "/people/counterparties/{id}/logo",
    response_model=CounterpartyCard,
    operation_id="uploadCounterpartyLogo",
)
async def upload_logo(
    id: CompanyId, request: Request, authed: RequisitesWriter
) -> CounterpartyCard:
    body, content_type = await _multipart(request)
    response = await ErpCompany(authed.call).request(
        "PUT", f"parties/organizations/{id}/logo/", content=body, content_type=content_type
    )
    return to_card(response.json())


@router.delete(
    "/people/counterparties/{id}/logo",
    response_model=CounterpartyCard,
    operation_id="deleteCounterpartyLogo",
)
async def delete_logo(id: CompanyId, authed: RequisitesWriter) -> CounterpartyCard:
    return to_card(
        await ErpCompany(authed.call).data("DELETE", f"parties/organizations/{id}/logo/")
    )


@router.get(
    "/people/contacts/{id}/photo",
    response_class=Response,
    responses={200: {"content": {"image/webp": {}}}},
    operation_id="getContactPhoto",
)
async def get_photo(
    id: ContactId, authed: PhotoReader, size: Size = None, v: str | None = None
) -> Response:
    params = {"size": size} if size else None
    return _image(
        await ErpCompany(authed.call).request("GET", f"parties/people/{id}/photo/", params=params)
    )


def _photo(data: Any, fallback: str) -> ContactPhoto:
    row: dict[str, Any] = data if isinstance(data, dict) else {}
    ident = str(row.get("id", fallback))
    return ContactPhoto(id=ident, photo_url=contact_photo_url(ident, row.get("photo_version")))


@router.put(
    "/people/contacts/{id}/photo",
    response_model=ContactPhoto,
    operation_id="uploadContactPhoto",
)
async def upload_photo(id: ContactId, request: Request, authed: RequisitesWriter) -> ContactPhoto:
    body, content_type = await _multipart(request)
    response = await ErpCompany(authed.call).request(
        "PUT", f"parties/people/{id}/photo/", content=body, content_type=content_type
    )
    return _photo(response.json(), id)


@router.delete(
    "/people/contacts/{id}/photo",
    response_model=ContactPhoto,
    operation_id="deleteContactPhoto",
)
async def delete_photo(id: ContactId, authed: RequisitesWriter) -> ContactPhoto:
    return _photo(await ErpCompany(authed.call).data("DELETE", f"parties/people/{id}/photo/"), id)


async def logo_urls(authed: Authed, company_ids: list[int]) -> dict[int, str]:
    """Адреса логотипов компаний ERP одним запросом — для строк реестра, где компания пришла из CRM.

    ERP не ответил — строки без логотипа (буквы названия): картинка не должна ломать реестр.
    """
    ids = sorted(set(company_ids))
    urls: dict[int, str] = {}
    erp = ErpCompany(authed.call)
    for start in range(
        0, len(ids), LOGO_BATCH
    ):  # ERP берёт до 100 id за запрос; обрезать нельзя: пропадут свежие строки
        batch = ids[start : start + LOGO_BATCH]
        try:
            data = await erp.data(
                "GET",
                "parties/organizations/logos/",
                params={"ids": ",".join(str(i) for i in batch)},
            )
        except PlatformError:
            continue
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, dict):
            continue
        for key, version in results.items():
            url = company_logo_url(key, version)
            if url and str(key).isdigit():
                urls[int(key)] = url
    return urls

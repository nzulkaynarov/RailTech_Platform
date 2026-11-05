"""Реестр полномочий подписи (`/api/v1/signing…`, eds.yaml, тег `signing`; SIGN-2, ADR-0024 п. 1–2, 8); правила —
`services/signing_registry.py`, подбор подписанта — `services/signing_resolve.py`.

Ведёт реестр держатель права `signing.manage` (код каталога ролей `eds.signing.manage`, ADR-0012). Подбор «кто вправе
подписать» экрану настроек нужен для проверки правил; шаг подписи маршрута зовёт тот же сервис напрямую, без HTTP.
"""

import datetime as dt
import uuid
from collections.abc import Callable, Coroutine
from decimal import Decimal
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_storage, require_permission
from app.errors import invalid_fields
from app.models import Employee
from app.schemas.common import Amount, Currency
from app.schemas.signing import (
    KindCode,
    SigningAuthorityDetail,
    SigningAuthorityIn,
    SigningAuthorityList,
    SigningAuthorityPatch,
    SigningResolution,
    SigningRevokeIn,
    SigningSetupHint,
    StatusFilter,
)
from app.security.permissions import EdsPermission as P
from app.services import dictionaries, files, signing_registry, signing_resolve
from app.services.storage import ObjectStorage


class SizeGuardRoute(APIRoute):
    """413 по `Content-Length` до разбора multipart (как у загрузки файлов документов)."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > files.MAX_BYTES + MULTIPART_OVERHEAD:
                raise files.too_large()
            return await handler(request)

        return guarded


MULTIPART_OVERHEAD = 1024 * 1024  # границы и поля multipart сверх самого файла
CHUNK = 1024 * 1024


async def read_limited(upload: UploadFile) -> bytes:
    """Прочитать загруженное, остановившись на первом байте сверх лимита (413)."""
    data = bytearray()
    while chunk := await upload.read(CHUNK):
        data += chunk
        if len(data) > files.MAX_BYTES:
            raise files.too_large()
    return bytes(data)


router = APIRouter(prefix="/api/v1/signing", tags=["signing"])
upload_router = APIRouter(prefix="/api/v1/signing", tags=["signing"], route_class=SizeGuardRoute)

Manager = Annotated[Employee, Depends(require_permission(P.SIGNING_MANAGE))]
Session = Annotated[AsyncSession, Depends(get_session)]
Storage = Annotated[ObjectStorage, Depends(get_storage)]
AuthorityId = uuid.UUID


@router.get("/authorities", response_model=SigningAuthorityList, operation_id="listSigningAuthorities")
async def list_authorities(
    _: Manager,
    session: Session,
    status: Annotated[StatusFilter, Query()] = "all",
    crm_user_id: Annotated[int | None, Query()] = None,
) -> SigningAuthorityList:
    return await signing_registry.list_authorities(session, status=status, crm_user_id=crm_user_id)


@router.post(
    "/authorities", response_model=SigningAuthorityDetail, status_code=201, operation_id="createSigningAuthority"
)
async def create_authority(body: SigningAuthorityIn, employee: Manager, session: Session) -> SigningAuthorityDetail:
    async with session.begin():
        return await signing_registry.create(session, employee.crm_user_id, body)


@router.get("/authorities/{authority_id}", response_model=SigningAuthorityDetail, operation_id="getSigningAuthority")
async def get_authority(authority_id: AuthorityId, _: Manager, session: Session) -> SigningAuthorityDetail:
    return await signing_registry.detail(session, authority_id)


@router.patch(
    "/authorities/{authority_id}", response_model=SigningAuthorityDetail, operation_id="updateSigningAuthority"
)
async def update_authority(
    authority_id: AuthorityId, body: SigningAuthorityPatch, employee: Manager, session: Session
) -> SigningAuthorityDetail:
    async with session.begin():
        return await signing_registry.update(session, employee.crm_user_id, authority_id, body)


@router.post(
    "/authorities/{authority_id}/revoke", response_model=SigningAuthorityDetail, operation_id="revokeSigningAuthority"
)
async def revoke_authority(
    authority_id: AuthorityId, body: SigningRevokeIn, employee: Manager, session: Session
) -> SigningAuthorityDetail:
    async with session.begin():
        return await signing_registry.revoke(session, employee.crm_user_id, authority_id, body.reason)


@upload_router.post(
    "/authorities/{authority_id}/basis-file",
    response_model=SigningAuthorityDetail,
    operation_id="uploadSigningBasisFile",
)
async def upload_basis_file(
    authority_id: AuthorityId,
    employee: Manager,
    session: Session,
    storage: Storage,
    file: Annotated[UploadFile, File()],
) -> SigningAuthorityDetail:
    item = files.Upload(name=file.filename or "", content_type=file.content_type or "", data=await read_limited(file))
    async with session.begin():
        return await signing_registry.set_file(session, storage, employee.crm_user_id, authority_id, item)


@router.get("/authorities/{authority_id}/basis-file", operation_id="downloadSigningBasisFile")
async def download_basis_file(
    authority_id: AuthorityId,
    _: Manager,
    session: Session,
    storage: Storage,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> StreamingResponse:
    found = await signing_registry.file_version(session, authority_id, version)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(found.name)}",
        "ETag": f'"{found.sha256}"',
        "Content-Length": str(found.size),
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(storage.stream(found.s3_key), media_type=found.content_type, headers=headers)


@router.get("/resolve", response_model=SigningResolution, operation_id="resolveSigners")
async def resolve_signers(
    _: Manager,
    session: Session,
    kind: Annotated[KindCode, Query()],
    amount: Annotated[Amount | None, Query()] = None,
    currency: Annotated[Currency | None, Query()] = None,
    on_date: Annotated[dt.date | None, Query()] = None,
) -> SigningResolution:
    """Кто вправе подписать `kind` на сумму `amount` на `on_date` (по умолчанию — сегодня) с учётом замещения."""
    if (amount is None) != (currency is None):
        raise invalid_fields("Сумма задаётся вместе с валютой.", **{"currency" if amount else "amount": "required"})
    if amount is not None and Decimal(amount) <= 0:
        raise invalid_fields("Сумма должна быть больше нуля.", amount="must_be_positive")
    item = await dictionaries.find(session, signing_registry.KINDS, kind, active_only=False)
    return await signing_resolve.resolve(
        session,
        kind=kind,
        amount=None if amount is None else Decimal(amount),
        currency=currency,
        on_date=on_date or signing_registry.today(),
        kind_label=item.name_ru if item else None,
    )


@router.get("/setup-hint", response_model=SigningSetupHint, operation_id="getSigningSetupHint")
async def get_setup_hint(_: Manager, session: Session) -> SigningSetupHint:
    return await signing_registry.setup_hint(session)

"""EDS · Права подписи (контракт BFF: тег `signing`, `/eds/signing/…`; SIGN-2, ADR-0024 п. 1–2, 8).

Эталоны — Directum RX «Право подписи», 1С:Документооборот (замещение), SAP release strategy (порог
суммы). BFF не решает: инварианты основания (доверенность — номер, дата, срок до 3 лет), лимит,
срок, замещение, журнал и «кто вправе подписать» — в EDS. Здесь — раздел каталога
`eds.signing.manage`, ids строками, лимит как `EdsMoney`, перевод ошибок EDS. Файл основания: BFF
читает тело потоком до предела, multipart не разбирает; скачивание — потоком.
"""

import uuid
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import ValidationError

from app.api.eds_documents import FileStream, _read_limited
from app.deps import Authed, require
from app.eds_documents import API, EdsProxy, eds_error
from app.errors import PlatformError, backend_unavailable
from app.schemas_eds_signing import (
    KindCode,
    SigningAuthorityDetail,
    SigningAuthorityIn,
    SigningAuthorityList,
    SigningAuthorityPatch,
    SigningResolution,
    SigningRevokeIn,
    SigningSetupHint,
    StatusFilter,
    UserId,
    to_authority,
    to_detail,
    to_hint,
    to_resolution,
)

router = APIRouter(prefix="/eds/signing", tags=["signing"])

Keeper = Annotated[Authed, Depends(require("eds.signing.manage", "full"))]
AuthorityId = Annotated[uuid.UUID, Path(alias="id")]
BASE = f"{API}/signing"


def _proxy(authed: Authed) -> EdsProxy:
    return EdsProxy(authed.call)


def _safe[T](make: Callable[[Any], T], raw: Any) -> T:
    """Ответ EDS, разобранный `make`; не та форма — `BACKEND_UNAVAILABLE`."""
    try:
        return make(raw)
    except ValidationError as exc:
        raise backend_unavailable("eds", "bad_signing") from exc


@router.get(
    "/authorities", response_model=SigningAuthorityList, operation_id="listSigningAuthorities"
)
async def list_authorities(
    authed: Keeper,
    status_filter: Annotated[StatusFilter, Query(alias="status")] = "all",
    holder_id: Annotated[UserId | None, Query()] = None,
) -> SigningAuthorityList:
    params: dict[str, Any] = {"status": status_filter}
    if holder_id:
        params["crm_user_id"] = int(holder_id)
    raw = await _proxy(authed).request("GET", f"{BASE}/authorities", params=params)
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        raise backend_unavailable("eds", "bad_signing")
    return SigningAuthorityList(items=[_safe(to_authority, item) for item in items])


@router.post(
    "/authorities",
    response_model=SigningAuthorityDetail,
    status_code=status.HTTP_201_CREATED,
    operation_id="createSigningAuthority",
)
async def create_authority(authed: Keeper, body: SigningAuthorityIn) -> SigningAuthorityDetail:
    raw = await _proxy(authed).request(
        "POST", f"{BASE}/authorities", expected=201, json=body.for_eds()
    )
    return _safe(to_detail, raw)


@router.get(
    "/authorities/{id}", response_model=SigningAuthorityDetail, operation_id="getSigningAuthority"
)
async def get_authority(authed: Keeper, authority_id: AuthorityId) -> SigningAuthorityDetail:
    raw = await _proxy(authed).request("GET", f"{BASE}/authorities/{authority_id}")
    return _safe(to_detail, raw)


@router.patch(
    "/authorities/{id}",
    response_model=SigningAuthorityDetail,
    operation_id="updateSigningAuthority",
)
async def update_authority(
    authed: Keeper, authority_id: AuthorityId, body: SigningAuthorityPatch
) -> SigningAuthorityDetail:
    raw = await _proxy(authed).request(
        "PATCH", f"{BASE}/authorities/{authority_id}", json=body.for_eds()
    )
    return _safe(to_detail, raw)


@router.post(
    "/authorities/{id}/revoke",
    response_model=SigningAuthorityDetail,
    operation_id="revokeSigningAuthority",
)
async def revoke_authority(
    authed: Keeper, authority_id: AuthorityId, body: SigningRevokeIn
) -> SigningAuthorityDetail:
    raw = await _proxy(authed).request(
        "POST", f"{BASE}/authorities/{authority_id}/revoke", json={"reason": body.reason}
    )
    return _safe(to_detail, raw)


@router.post(
    "/authorities/{id}/basis-file",
    response_model=SigningAuthorityDetail,
    operation_id="uploadSigningBasisFile",
)
async def upload_basis_file(
    request: Request, authed: Keeper, authority_id: AuthorityId
) -> SigningAuthorityDetail:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise PlatformError(
            "VALIDATION_FAILED",
            "Файл нужно передать формой multipart.",
            status_code=422,
            details={"fields": ["file"], "reason": "multipart_required"},
        )
    body = await _read_limited(request)
    raw = await _proxy(authed).request(
        "POST",
        f"{BASE}/authorities/{authority_id}/basis-file",
        content=body,
        content_type=content_type,
    )
    return _safe(to_detail, raw)


@router.get(
    "/authorities/{id}/basis-file",
    response_class=StreamingResponse,
    responses={200: {"content": {"application/octet-stream": {}}}},
    operation_id="downloadSigningBasisFile",
)
async def download_basis_file(authed: Keeper, authority_id: AuthorityId) -> StreamingResponse:
    response = await _proxy(authed).raw(
        "GET", f"{BASE}/authorities/{authority_id}/basis-file", stream=True
    )
    if response.status_code != 200:
        try:
            await response.aread()
            raise eds_error(response)
        finally:
            await response.aclose()
    headers = {
        "Content-Disposition": response.headers.get("content-disposition") or "attachment",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
        "Cache-Control": "private, no-store",
    }
    return FileStream(response, headers, "application/octet-stream")


@router.get("/resolve", response_model=SigningResolution, operation_id="resolveSigners")
async def resolve_signers(
    authed: Keeper,
    kind: Annotated[KindCode, Query()],
    amount: Annotated[str | None, Query(pattern=r"^\d+\.\d{2}$")] = None,
    currency: Annotated[str | None, Query(pattern=r"^[A-Z]{3}$")] = None,
    on_date: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}-\d{2}$")] = None,
) -> SigningResolution:
    params = {
        k: v
        for k, v in {
            "kind": kind,
            "amount": amount,
            "currency": currency,
            "on_date": on_date,
        }.items()
        if v
    }
    raw = await _proxy(authed).request("GET", f"{BASE}/resolve", params=params)
    return _safe(to_resolution, raw)


@router.get("/setup-hint", response_model=SigningSetupHint, operation_id="getSigningSetupHint")
async def get_setup_hint(authed: Keeper) -> SigningSetupHint:
    raw = await _proxy(authed).request("GET", f"{BASE}/setup-hint")
    return _safe(to_hint, raw)

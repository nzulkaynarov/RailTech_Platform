"""Файлы документов с версиями: `/api/v1/files…` (eds.yaml, тег `files`); правила — `services/files.py`."""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, get_storage, require_permission
from app.models import Employee
from app.schemas.common import FileRef
from app.schemas.files import FileVersions
from app.security.permissions import EdsPermission as P
from app.services import files, idempotency
from app.services.storage import ObjectStorage


class SizeGuardRoute(APIRoute):
    """Отказ 413 по `Content-Length` до разбора multipart: лишние мегабайты не читаются и не пишутся на диск."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def guarded(request: Request) -> Response:
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > files.MAX_BYTES + MULTIPART_OVERHEAD:
                raise files.too_large()
            return await handler(request)

        return guarded


router = APIRouter(prefix="/api/v1", tags=["files"])
upload_router = APIRouter(prefix="/api/v1", tags=["files"], route_class=SizeGuardRoute)
MULTIPART_OVERHEAD = 1024 * 1024  # границы и поля multipart сверх самого файла

IdemKey = Annotated[str | None, Header(alias="Idempotency-Key", min_length=8, max_length=128)]
Uploader = Annotated[
    Employee,
    Depends(
        require_permission(
            P.LETTERS_REGISTER, P.LETTERS_RESOLVE, P.MEMOS_CREATE, P.MEMOS_APPROVE, P.APPROVALS_DECIDE, P.FILES_UPLOAD
        )
    ),
]
Reader = Annotated[
    Employee,
    # `files.upload` (D1-2b): только свои файлы — чужой непривязанный и файлы писем без `letters.read`
    # дают 404 (`can_view_file`).
    Depends(
        require_permission(
            P.LETTERS_READ, P.MEMOS_CREATE, P.MEMOS_APPROVE, P.APPROVALS_DECIDE, P.REGISTRY_READ, P.FILES_UPLOAD
        )
    ),
]
Session = Annotated[AsyncSession, Depends(get_session)]
Storage = Annotated[ObjectStorage, Depends(get_storage)]
CHUNK = 1024 * 1024


async def _read_limited(upload: UploadFile) -> bytes:
    """Прочитать загруженное, остановившись на первом байте сверх лимита (413)."""
    data = bytearray()
    while chunk := await upload.read(CHUNK):
        data += chunk
        if len(data) > files.MAX_BYTES:
            raise files.too_large()
    return bytes(data)


@upload_router.post("/files", response_model=FileRef, status_code=201, operation_id="uploadFile")
async def upload_file(
    employee: Uploader,
    session: Session,
    storage: Storage,
    file: Annotated[UploadFile, File()],
    version_of: Annotated[uuid.UUID | None, Form()] = None,
    idempotency_key: IdemKey = None,
) -> Any:
    item = files.Upload(
        name=file.filename or "",
        content_type=file.content_type or "",
        data=await _read_limited(file),
        version_of=version_of,
    )
    async with session.begin():

        async def store() -> FileRef:
            return await files.upload(session, storage, employee, item)

        return await idempotency.run(
            session,
            crm_user_id=employee.crm_user_id,
            scope="POST /files",
            key=idempotency_key,
            request_hash=idempotency.body_hash(item.name, item.content_type, str(version_of), files.digest(item.data)),
            status_code=201,
            action=store,
        )


@router.get("/files/{file_id}", operation_id="downloadFile", response_class=StreamingResponse)
async def download_file(
    file_id: uuid.UUID,
    employee: Reader,
    session: Session,
    storage: Storage,
    version: Annotated[int | None, Query(ge=1)] = None,
) -> StreamingResponse:
    await files.load_visible(session, employee, file_id)
    found = await files.get_version(session, file_id, version)
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(found.name)}",
        "ETag": f'"{found.sha256}"',
        "Content-Length": str(found.size),
        "X-Content-Type-Options": "nosniff",
    }
    return StreamingResponse(storage.stream(found.s3_key), media_type=found.content_type, headers=headers)


@router.get("/files/{file_id}/versions", response_model=FileVersions, operation_id="listFileVersions")
async def list_file_versions(file_id: uuid.UUID, employee: Reader, session: Session) -> FileVersions:
    await files.load_visible(session, employee, file_id)
    return FileVersions(items=await files.versions(session, file_id))

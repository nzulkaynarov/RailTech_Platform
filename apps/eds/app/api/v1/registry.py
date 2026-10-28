"""Реестр «Все документы»: `/api/v1/registry`, `/registry/export` (eds.yaml, тег `registry`)."""

import datetime as dt
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app import clock
from app.api.deps import get_session, require_permission
from app.errors import EdsError
from app.models import Employee
from app.schemas.pagination import Cursor, Limit
from app.schemas.registry import RegistryKind, RegistryPage
from app.security.permissions import EdsPermission as P
from app.services import journal, registry, registry_export

router = APIRouter(prefix="/api/v1", tags=["registry"])

Session = Annotated[AsyncSession, Depends(get_session)]
Status = Annotated[str, StringConstraints(pattern=r"^[a-z_]+$")]


async def filters(
    kind: Annotated[list[RegistryKind] | None, Query()] = None,
    status: Annotated[list[Status] | None, Query()] = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    responsible: int | None = None,
    crm_client_id: int | None = None,
    number: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> registry.Filters:
    return registry.Filters(
        kinds=kind or [],
        statuses=status or [],
        date_from=date_from,
        date_to=date_to,
        responsible=responsible,
        crm_client_id=crm_client_id,
        number=number,
        q=q,
    )


Filter = Annotated[registry.Filters, Depends(filters)]


@router.get("/registry", response_model=RegistryPage, operation_id="listRegistry")
async def list_registry(
    employee: Annotated[Employee, Depends(require_permission(P.REGISTRY_READ))],
    session: Session,
    flt: Filter,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> RegistryPage:
    return await registry.list_page(session, employee, flt, cursor=cursor, limit=limit)


@router.get("/registry/export", operation_id="exportRegistry", response_class=Response)
async def export_registry(
    employee: Annotated[Employee, Depends(require_permission(P.REGISTRY_EXPORT))],
    session: Session,
    flt: Filter,
    format: Annotated[str, Query(pattern="^(xlsx|csv)$")] = "xlsx",
) -> Response:
    async with session.begin():
        items = await registry.export_rows(session, employee, flt)
        if items is None:
            raise EdsError(
                "VALIDATION_FAILED",
                "Слишком много строк для экспорта: уточните фильтры.",
                status_code=422,
                details={"reason": "export_too_large", "limit": registry.EXPORT_LIMIT},
            )
        await journal.record(
            session, "registry.export", by=employee.crm_user_id, comment=f"{format}, строк: {len(items)}"
        )
    if format == "csv":
        body, media = registry_export.to_csv(items), registry_export.CSV_TYPE
    else:
        body, media = registry_export.to_xlsx(items), registry_export.XLSX_TYPE
    name = quote(f"registry-{clock.company_date(clock.now()).isoformat()}.{format}")
    return Response(
        content=body, media_type=media, headers={"Content-Disposition": f"attachment; filename*=UTF-8''{name}"}
    )

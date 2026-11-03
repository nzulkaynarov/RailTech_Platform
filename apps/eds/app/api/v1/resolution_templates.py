"""Шаблоны резолюций (`/api/v1/resolution-templates…`, eds.yaml, тег `letters`; EDS-REG, R2); правила —
`services/resolution_templates.py`."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session, require_permission
from app.models import Employee
from app.schemas.resolution_templates import ResolutionTemplate, ResolutionTemplateIn, ResolutionTemplateList
from app.security.permissions import EdsPermission as P
from app.services import resolution_templates

router = APIRouter(prefix="/api/v1/resolution-templates", tags=["letters"])

# Директор и делопроизводитель — свои и общие; администратор — общие. Сужение по виду шаблона — в сервисе.
Author = Annotated[Employee, Depends(require_permission(P.LETTERS_RESOLVE, P.LETTERS_REGISTER, P.BUS_MANAGE))]
Session = Annotated[AsyncSession, Depends(get_session)]


@router.get("", response_model=ResolutionTemplateList, operation_id="listResolutionTemplates")
async def list_resolution_templates(employee: Author, session: Session) -> ResolutionTemplateList:
    return await resolution_templates.list_for(session, employee)


@router.post(
    "",
    response_model=ResolutionTemplate,
    status_code=status.HTTP_201_CREATED,
    operation_id="createResolutionTemplate",
)
async def create_resolution_template(
    body: ResolutionTemplateIn, employee: Author, session: Session
) -> ResolutionTemplate:
    async with session.begin():
        return await resolution_templates.create(session, employee, body)


@router.put("/{template_id}", response_model=ResolutionTemplate, operation_id="updateResolutionTemplate")
async def update_resolution_template(
    template_id: uuid.UUID, body: ResolutionTemplateIn, employee: Author, session: Session
) -> ResolutionTemplate:
    async with session.begin():
        return await resolution_templates.update(session, employee, template_id, body)


@router.delete(
    "/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    operation_id="deleteResolutionTemplate",
)
async def delete_resolution_template(template_id: uuid.UUID, employee: Author, session: Session) -> Response:
    async with session.begin():
        await resolution_templates.delete(session, employee, template_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

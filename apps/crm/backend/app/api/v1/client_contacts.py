"""Контакты клиента (Q-011) и подсказки «Из Telegram» (Q-020); мутации — с аудитом."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import ContainerDep, require
from app.schemas.clients import ClientContacts, ContactIn
from app.schemas.kb_admin import Created
from app.schemas.leads import ActionResult
from app.security.principal import Principal

router = APIRouter(prefix="/api/v1", tags=["clients"])

ClientReader = Annotated[Principal, Depends(require("clients", "read"))]
ClientWriter = Annotated[Principal, Depends(require("clients", "write"))]


@router.get("/clients/{client_id}/contacts", response_model=ClientContacts)
async def list_client_contacts(
    client_id: int, _: ClientReader, container: ContainerDep
) -> ClientContacts:
    """Контакты (основной первым) и подтверждённые Telegram-аккаунты с номером для «Добавить»."""
    return await container.contact_service.overview(client_id)


@router.post(
    "/clients/{client_id}/contacts", response_model=Created, status_code=status.HTTP_201_CREATED
)
async def create_client_contact(
    client_id: int, body: ContactIn, who: ClientWriter, container: ContainerDep
) -> Created:
    return Created(id=await container.contact_service.create(who, client_id, body))


@router.put("/clients/{client_id}/contacts/{contact_id}", response_model=ActionResult)
async def update_client_contact(
    client_id: int, contact_id: int, body: ContactIn, who: ClientWriter, container: ContainerDep
) -> ActionResult:
    await container.contact_service.update(who, client_id, contact_id, body)
    return ActionResult()


@router.delete("/clients/{client_id}/contacts/{contact_id}", response_model=ActionResult)
async def delete_client_contact(
    client_id: int, contact_id: int, who: ClientWriter, container: ContainerDep
) -> ActionResult:
    await container.contact_service.delete(who, client_id, contact_id)
    return ActionResult()

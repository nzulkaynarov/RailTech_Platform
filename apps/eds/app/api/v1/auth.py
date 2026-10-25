"""Вход: обмен SSO-токена сотрудника CRM на токен доступа EDS (`POST /api/v1/auth/sso/exchange`)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.deps import get_container
from app.container import Container
from app.services import sso

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class SsoExchangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=16, max_length=4096)


class AccessToken(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — тип схемы авторизации, не секрет
    expires_in: Literal[900] = 900


@router.post("/sso/exchange", response_model=AccessToken, operation_id="ssoExchange")
async def sso_exchange(body: SsoExchangeIn, container: Annotated[Container, Depends(get_container)]) -> AccessToken:
    result = await sso.exchange(container.session_factory, container.settings, body.token)
    return AccessToken(access_token=result.access_token)

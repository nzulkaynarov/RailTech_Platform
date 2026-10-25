"""Живость сервиса и базы: `GET /health` (healthcheck контейнера, compose, smoke)."""

import asyncio
from typing import Literal

import structlog
from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from app import db
from app.api.deps import get_container

log = structlog.get_logger(__name__)
router = APIRouter(tags=["system"])

Check = Literal["ok", "unavailable"]


class Health(BaseModel):
    status: Check
    version: str
    checks: dict[str, Check]


@router.get(
    "/health",
    response_model=Health,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": Health}},
)
async def health(request: Request, response: Response) -> Health:
    container = get_container(request)
    database: Check = "ok"
    try:
        await asyncio.wait_for(db.ping(container.engine), timeout=container.settings.health_timeout_s)
    except Exception as exc:  # noqa: BLE001 — любая причина = база недоступна
        log.warning("health_database_unavailable", error=type(exc).__name__)
        database = "unavailable"
    if database != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Health(status=database, version=container.settings.version, checks={"database": database})

"""Служебные эндпоинты: liveness и readiness (SPEC §13)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel

from app.services.readiness import ReadinessService

router = APIRouter(tags=["health"])

CheckStatus = Literal["ok", "fail"]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: CheckStatus
    checks: dict[str, CheckStatus]


def get_readiness(request: Request) -> ReadinessService:
    service: ReadinessService = request.app.state.readiness
    return service


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse()


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
async def ready(
    response: Response,
    readiness: Annotated[ReadinessService, Depends(get_readiness)],
) -> ReadyResponse:
    report = await readiness.check()
    if not report.ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ok" if report.ok else "fail",
        checks={name: "ok" if ok else "fail" for name, ok in report.checks.items()},
    )

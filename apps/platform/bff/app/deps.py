"""Зависимости FastAPI: общие ресурсы живут в `app.state` (создаются в lifespan)."""

from typing import Annotated

from fastapi import Depends, Request
from redis.asyncio import Redis

from app.clients import CrmClient, ErpClient


def get_redis(request: Request) -> Redis:
    redis: Redis = request.app.state.redis
    return redis


def get_crm(request: Request) -> CrmClient:
    crm: CrmClient = request.app.state.crm
    return crm


def get_erp(request: Request) -> ErpClient:
    erp: ErpClient = request.app.state.erp
    return erp


RedisDep = Annotated[Redis, Depends(get_redis)]
CrmDep = Annotated[CrmClient, Depends(get_crm)]
ErpDep = Annotated[ErpClient, Depends(get_erp)]

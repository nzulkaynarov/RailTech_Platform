"""GET /api/v1/about — «О системе»: версия Платформы и состояние сервисов.

W-REL, контракт: operationId getAbout.
"""

import asyncio
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.deps import AuthedDep, CrmDep, EdsDep, ErpDep, SettingsDep
from app.release import SHORT_SHA, Release, is_sha, release_of

router = APIRouter(tags=["system"])

ServiceKey = Literal["bff", "crm", "erp", "eds"]
ServiceState = Literal["ok", "fail", "disabled"]


class ServiceVersion(BaseModel):
    key: ServiceKey
    status: ServiceState
    version: str | None = None


class About(BaseModel):
    release: Release
    services: list[ServiceVersion]
    checked_at: datetime


def _service(key: ServiceKey, state: tuple[bool, str | None] | None) -> ServiceVersion:
    if state is None:
        return ServiceVersion(key=key, status="disabled")
    ok, version = state
    # EDS сообщает тег выкладки — полный sha; на экране он короткий, как у релиза.
    if version and is_sha(version):
        version = version[:SHORT_SHA]
    return ServiceVersion(key=key, status="ok" if ok else "fail", version=version)


@router.get(
    "/about", response_model=About, response_model_exclude_none=True, operation_id="getAbout"
)
async def get_about(
    _: AuthedDep, settings: SettingsDep, crm: CrmDep, erp: ErpDep, eds: EdsDep
) -> About:
    """Сессия нужна, прав раздела — нет.

    Источник не ответил — `fail`, а не ошибка: экран показывает остальное.
    """

    async def off() -> None:
        return None

    crm_state, erp_state, eds_state = await asyncio.gather(
        crm.health_info(), erp.health_info(), eds.health_info() if eds else off()
    )
    return About(
        release=release_of(settings),
        services=[
            ServiceVersion(key="bff", status="ok", version=__version__),
            _service("crm", crm_state),
            _service("erp", erp_state),
            _service("eds", eds_state),
        ],
        checked_at=datetime.now(UTC),
    )

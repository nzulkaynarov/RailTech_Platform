"""Служебные консоли сервисов через Платформу (OPS-CONSOLE, DECISIONS 2026-11-03).

Консоли внутренних сервисов публикуются на домене Платформы по пути `/console/<ключ>/`, а не на
отдельных поддоменах. Перед каждым запросом туда Caddy спрашивает `GET /api/v1/consoles/{key}/auth`
(`forward_auth`): пропускает только сотрудника с живой сессией Платформы и правом `admin: full`.
Своя защита консоли (мастер-ключ LiteLLM, вход Django admin) остаётся — Платформа учётных данных не
передаёт. Первое открытие консоли за `AUDIT_WINDOW_SECONDS` сессии — запись в журнале аудита CRM.
"""

from typing import Annotated, Final, Literal

import structlog
from fastapi import APIRouter, Depends, Path, Response
from pydantic import BaseModel
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.deps import Authed, RedisDep, SettingsDep, require
from app.errors import PlatformError

router = APIRouter(tags=["integrations"])
log = structlog.get_logger()

ConsoleKey = Literal["litellm", "erp"]
# Адрес входа в консоль на домене Платформы; маршрут и проверка — infra/caddy/Caddyfile.prod.
CONSOLE_URLS: Final[dict[str, str]] = {
    "litellm": "/console/litellm/ui/",
    "erp": "/console/erp/admin/",
}
# Одно «открытие» — первый запрос к консоли за полчаса сессии: Caddy спрашивает на каждый файл.
AUDIT_WINDOW_SECONDS: Final = 30 * 60
NO_STORE: Final = {"Cache-Control": "no-store"}

Admin = Annotated[Authed, Depends(require("admin", "full"))]


class NoStoreConsoleAuth:
    """`Cache-Control: no-store` на любом ответе проверки консоли, в том числе на 401 и 403.

    Отказ, закэшированный браузером или прокси, пускал бы или не пускал по чужому решению.
    """

    PREFIX: Final = "/api/v1/consoles/"

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not str(scope.get("path", "")).startswith(self.PREFIX):
            await self.app(scope, receive, send)
            return

        async def send_no_store(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (name, value)
                    for name, value in message.get("headers", [])
                    if name.lower() != b"cache-control"
                ]
                headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_no_store)


class ServiceConsole(BaseModel):
    key: ConsoleKey
    url: str


class ServiceConsoleList(BaseModel):
    items: list[ServiceConsole]


def enabled_consoles(raw: str) -> list[str]:
    """Ключи из `PLATFORM_CONSOLES` в порядке справочника; неизвестные отбрасываются."""
    wanted = {part.strip() for part in raw.split(",") if part.strip()}
    return [key for key in CONSOLE_URLS if key in wanted]


@router.get(
    "/admin/consoles", response_model=ServiceConsoleList, operation_id="listServiceConsoles"
)
async def list_consoles(_: Admin, settings: SettingsDep, response: Response) -> ServiceConsoleList:
    response.headers.update(NO_STORE)
    return ServiceConsoleList(
        items=[
            ServiceConsole(key=key, url=CONSOLE_URLS[key])
            for key in enabled_consoles(settings.consoles)
        ]
    )


async def _audit_once(authed: Authed, redis: RedisDep, key: str) -> None:
    """Запись `console.open` в журнал CRM — одна на окно; сбой журнала не закрывает консоль."""
    marker = f"pf:console:{authed.sid}:{key}"
    if not await redis.set(marker, "1", ex=AUDIT_WINDOW_SECONDS, nx=True):
        return
    user = authed.data.user_id
    try:
        response = await authed.call(
            "crm", "POST", "/api/v1/audit/console-open", json={"console": key}
        )
        ok = response.status_code == 204
    except PlatformError:
        ok = False
    if ok:
        log.info("console_open", console=key, user_id=user)
        return
    # Журнал не принял запись — отметку снимаем, следующий запрос попробует снова.
    await redis.delete(marker)
    log.warning("console_open_audit_failed", console=key, user_id=user)


@router.get("/consoles/{key}/auth", status_code=204, operation_id="authorizeServiceConsole")
async def authorize_console(
    authed: Admin,
    settings: SettingsDep,
    redis: RedisDep,
    key: Annotated[str, Path(max_length=32)],
) -> Response:
    """`forward_auth` Caddy: 204 — пропустить; 401/403 — сессия и право; 404 — консоль выключена."""
    if key not in enabled_consoles(settings.consoles):
        raise PlatformError(
            "NOT_FOUND", "Консоль не подключена.", status_code=404, details={"console": key}
        )
    await _audit_once(authed, redis, key)
    return Response(status_code=204, headers=NO_STORE)

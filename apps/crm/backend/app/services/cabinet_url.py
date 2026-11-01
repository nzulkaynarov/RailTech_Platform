"""Адрес кабинета клиента (D17G-3, гейт D1-7): где он берётся, сохранение и проверка доступности.

Без адреса приглашение в кабинет и кнопка «Открыть кабинет» под сообщениями бота не уходят
(`erp_invite_delivery`, `erp_bot_messages`). Адрес задаёт администратор в мастере «Первый запуск»
или в «Подключениях» (DECISIONS 2026-10-28: настройка интеграций — через интерфейс); не задан —
берётся из окружения (`CABINET_PUBLIC_URL` / `CABINET_DOMAIN`), как адрес CRM (W15-H8a). Хранится
в `company.cabinet_url` (раздел «Компания»), меняется только это поле.

Проверка — `GET <адрес>/health` с сервера CRM: кабинет (nginx `apps/cabinet/nginx.conf`) отвечает
`200 healthy`. Ответ наружу не отдаётся — только итог и код HTTP.
"""

from dataclasses import dataclass
from typing import Final, Literal

import httpx
import structlog

from app.domain.urls import is_http_url
from app.security.audit import Actor
from app.services.settings import SettingsService

logger = structlog.get_logger(__name__)

CHECK_TIMEOUT_S: Final = 5.0
HEALTH_BODY: Final = "healthy"

Source = Literal["saved", "env", "none"]
CheckResult = Literal["ok", "not_set", "unreachable", "bad_status", "not_cabinet"]


@dataclass(frozen=True, slots=True)
class CabinetAddress:
    url: str | None
    source: Source
    env_url: str | None


@dataclass(frozen=True, slots=True)
class CabinetCheck:
    result: CheckResult
    url: str | None
    status_code: int | None = None


class CabinetUrlService:
    def __init__(
        self,
        settings: SettingsService,
        env_url: str | None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._env_url = env_url
        self._transport = transport

    async def address(self) -> CabinetAddress:
        saved = str((await self._settings.raw())["company"].get("cabinet_url") or "").strip()
        if saved:
            return CabinetAddress(saved, "saved", self._env_url)
        if self._env_url:
            return CabinetAddress(self._env_url, "env", self._env_url)
        return CabinetAddress(None, "none", None)

    async def save(self, url: str, user_id: int | None, actor: Actor | None) -> CabinetAddress:
        """Записать только `company.cabinet_url`; пусто — вернуть адрес из окружения. Неверный
        адрес — `ValueError`."""
        company = dict((await self._settings.raw())["company"])
        company["cabinet_url"] = url.strip().rstrip("/")
        await self._settings.update("company", company, user_id, actor)
        return await self.address()

    async def check(self, url: str | None = None) -> CabinetCheck:
        """Открывается ли кабинет по адресу (`url`, иначе действующий): `GET /health` с сервера."""
        target = (url or "").strip().rstrip("/") or (await self.address()).url
        if not target:
            return CabinetCheck("not_set", None)
        if not is_http_url(target):
            return CabinetCheck("unreachable", target)
        try:
            async with httpx.AsyncClient(
                timeout=CHECK_TIMEOUT_S,
                follow_redirects=True,
                max_redirects=3,
                transport=self._transport,
            ) as client:
                response = await client.get(f"{target}/health")
        except httpx.HTTPError as exc:
            logger.info("cabinet_url_check_failed", error=type(exc).__name__)
            return CabinetCheck("unreachable", target)
        if response.status_code != 200:
            return CabinetCheck("bad_status", target, response.status_code)
        if not response.text.strip().startswith(HEALTH_BODY):
            return CabinetCheck("not_cabinet", target, 200)
        return CabinetCheck("ok", target, 200)

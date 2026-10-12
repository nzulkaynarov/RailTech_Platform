"""Каталог алиасов LiteLLM: алиас → провайдер и модель (учёт расходов, лимиты, «Модели ИИ»).

Источник — `GET /model/info` прокси (мастер-ключ из настроек процесса). Это единственное
место правды о моделях (`infra/litellm.config.yaml` читает только сам прокси), и оно же будет
верным, когда модели начнут храниться в БД LiteLLM. Из ответа берутся только алиас, модель и
провайдер — ключи провайдеров (`litellm_params.api_key`) никогда не копируются.

Кэш на 5 минут; при недоступности прокси — последнее известное значение (или пусто:
провайдер неизвестен → лимит провайдера не применяется, мягкий бюджет работает).
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from pydantic import AnyHttpUrl, SecretStr

logger = structlog.get_logger(__name__)
RETRY_S = 30.0


@dataclass(frozen=True, slots=True)
class ModelEntry:
    alias: str
    provider: str | None
    model: str | None


def parse_model_info(payload: Mapping[str, Any]) -> dict[str, ModelEntry]:
    """Ответ `/model/info` → алиас: (провайдер, модель). Мусорные записи пропускаются."""
    entries: dict[str, ModelEntry] = {}
    for item in payload.get("data") or []:
        if not isinstance(item, dict) or not isinstance(item.get("model_name"), str):
            continue
        params = item.get("litellm_params") or {}
        info = item.get("model_info") or {}
        model = params.get("model") if isinstance(params.get("model"), str) else None
        provider = info.get("litellm_provider") if isinstance(info, dict) else None
        if not isinstance(provider, str) or not provider:
            provider = model.split("/", 1)[0] if model and "/" in model else None
        alias = item["model_name"]
        entries.setdefault(alias, ModelEntry(alias=alias, provider=provider, model=model))
    return entries


class ModelCatalog:
    def __init__(
        self,
        base_url: AnyHttpUrl,
        master_key: SecretStr,
        ttl_s: float = 300.0,
        timeout_s: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = f"{str(base_url).rstrip('/')}/model/info"
        self._key = master_key
        self._ttl_s = ttl_s
        self._timeout_s = timeout_s
        self._clock = clock
        self._entries: dict[str, ModelEntry] = {}
        self._expires = 0.0

    async def entries(self) -> dict[str, ModelEntry]:
        if self._clock() < self._expires:
            return self._entries
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.get(
                    self._url, headers={"Authorization": f"Bearer {self._key.get_secret_value()}"}
                )
                response.raise_for_status()
            self._entries = parse_model_info(response.json())
            self._expires = self._clock() + self._ttl_s
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("litellm_model_info_failed", error=type(exc).__name__)
            self._expires = self._clock() + RETRY_S
        return self._entries

    async def provider(self, alias: str) -> str | None:
        entry = (await self.entries()).get(alias)
        return entry.provider if entry else None

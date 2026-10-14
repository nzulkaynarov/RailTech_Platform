"""API управления моделями LiteLLM (ADR-0020): `/model/info`, `/model/new`, `/model/delete`.

Центр внешних сервисов (ADR-0024, проверено на v1.105.0): `/provider/budgets` — расход и потолок
провайдера (`provider_budget_config`); `/router/settings` и `/config/update` с
`router_settings.model_group_alias` — перенаправление алиасов на запасную модель без перезапуска
(значение целиком принадлежит CRM); `/model/block`/`/model/unblock` — остановка deployment из БД.

Проверено на v1.104.2 (ADR-0020 «Проверка»): модели из БД прокси применяются без перезапуска,
ключи шифруются `LITELLM_SALT_KEY` и не возвращаются `/model/info`; запись с тем же алиасом
становится второй deployment в группе (не заменой) — поэтому замена = «создать новую, удалить
старые». Значения по умолчанию — `infra/litellm.models.yaml` (штатный формат `model_list`).

Ответы `/model/new` содержат зашифрованные параметры — они не логируются и не возвращаются.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import structlog
import yaml
from pydantic import AnyHttpUrl, SecretStr

logger = structlog.get_logger(__name__)
ENV_REF = "os.environ/"


class LiteLLMAdminError(Exception):
    """Прокси недоступен или отказал (статус и безопасный текст, без параметров запроса)."""

    def __init__(self, status: int | None, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


@dataclass(frozen=True, slots=True)
class Deployment:
    id: str
    alias: str
    model: str | None
    in_db: bool


@dataclass(frozen=True, slots=True)
class DefaultModel:
    """Запись `model_list` из `infra/litellm.models.yaml` — алиас и его параметры по умолчанию."""

    alias: str
    litellm_params: dict[str, Any]
    model_info: dict[str, Any] = field(default_factory=dict)

    @property
    def model(self) -> str:
        return str(self.litellm_params["model"])


def load_defaults(path: Path) -> dict[str, DefaultModel]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    out: dict[str, DefaultModel] = {}
    for item in data.get("model_list") or []:
        params = dict(item["litellm_params"])
        if not isinstance(params.get("model"), str):
            raise ValueError(f"{path}: litellm_params.model is required")
        out[item["model_name"]] = DefaultModel(
            alias=item["model_name"],
            litellm_params=params,
            model_info=dict(item.get("model_info") or {}),
        )
    return out


def env_keys(defaults: Mapping[str, DefaultModel]) -> dict[str, str]:
    """Провайдер → ссылка `os.environ/…` на ключ из env прокси (из значений по умолчанию)."""
    out: dict[str, str] = {}
    for d in defaults.values():
        key = d.litellm_params.get("api_key")
        if isinstance(key, str) and key.startswith(ENV_REF) and "/" in d.model:
            out.setdefault(d.model.split("/", 1)[0], key)
    return out


def parse_deployments(payload: Mapping[str, Any]) -> list[Deployment]:
    out: list[Deployment] = []
    for item in payload.get("data") or []:
        if not isinstance(item, dict) or not isinstance(item.get("model_name"), str):
            continue
        info = item.get("model_info") or {}
        params = item.get("litellm_params") or {}
        model_id = info.get("id") if isinstance(info, dict) else None
        if not isinstance(model_id, str):
            continue
        model = params.get("model") if isinstance(params, dict) else None
        out.append(
            Deployment(
                id=model_id,
                alias=item["model_name"],
                model=model if isinstance(model, str) else None,
                in_db=bool(info.get("db_model")),
            )
        )
    return out


@dataclass(frozen=True, slots=True)
class ProviderBudget:
    spend: float
    limit: float | None


def parse_budgets(payload: Mapping[str, Any]) -> dict[str, ProviderBudget]:
    providers = payload.get("providers")
    out: dict[str, ProviderBudget] = {}
    if not isinstance(providers, dict):
        return out
    for name, item in providers.items():
        if not isinstance(item, dict):
            continue
        spend = item.get("spend")
        limit = item.get("budget_limit")
        out[str(name)] = ProviderBudget(
            spend=float(spend) if isinstance(spend, int | float) else 0.0,
            limit=float(limit) if isinstance(limit, int | float) else None,
        )
    return out


class LiteLLMAdmin:
    def __init__(self, base_url: AnyHttpUrl, master_key: SecretStr, timeout_s: float = 10.0):
        self._base = str(base_url).rstrip("/")
        self._key = master_key
        self._timeout_s = timeout_s

    async def deployments(self) -> list[Deployment]:
        return parse_deployments(await self._call("GET", "/model/info", None))

    async def create(
        self, model_id: str, alias: str, params: Mapping[str, Any], info: Mapping[str, Any]
    ) -> None:
        body = {
            "model_name": alias,
            "litellm_params": dict(params),
            "model_info": {**info, "id": model_id},
        }
        await self._call("POST", "/model/new", body)

    async def delete(self, model_id: str) -> None:
        await self._call("POST", "/model/delete", {"id": model_id})

    async def provider_budgets(self) -> dict[str, ProviderBudget]:
        """Провайдер → расход и потолок за период; без `provider_budget_config` — пусто."""
        try:
            payload = await self._call("GET", "/provider/budgets", None)
        except LiteLLMAdminError as exc:
            if exc.status is not None and exc.status < 500 and exc.status not in (401, 403):
                return {}
            if exc.status == 500 and "provider budget config" in exc.detail.lower():
                return {}
            raise
        return parse_budgets(payload)

    async def router_aliases(self) -> dict[str, str]:
        """Текущий `model_group_alias` роутера (`GET /router/settings` → `current_values`)."""
        payload = await self._call("GET", "/router/settings", None)
        current = payload.get("current_values")
        aliases = current.get("model_group_alias") if isinstance(current, dict) else None
        if not isinstance(aliases, dict):
            return {}
        return {str(k): str(v) for k, v in aliases.items() if isinstance(v, str)}

    async def set_router_aliases(self, aliases: Mapping[str, str]) -> None:
        """Заменить `model_group_alias` целиком; применяется сразу и хранится в БД прокси."""
        body = {"router_settings": {"model_group_alias": dict(aliases)}}
        await self._call("POST", "/config/update", body)

    async def block(self, model_id: str) -> None:
        await self._call("POST", "/model/block", {"model_id": model_id})

    async def unblock(self, model_id: str) -> None:
        await self._call("POST", "/model/unblock", {"model_id": model_id})

    async def _call(self, method: str, path: str, body: object) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._key.get_secret_value()}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout_s) as client:
                response = await client.request(
                    method, f"{self._base}{path}", json=body, headers=headers
                )
        except httpx.HTTPError as exc:
            logger.warning("litellm_admin_unreachable", path=path, error=type(exc).__name__)
            raise LiteLLMAdminError(None, type(exc).__name__) from exc
        if response.status_code >= 400:
            detail = _error_text(response)
            logger.warning("litellm_admin_failed", path=path, status=response.status_code)
            raise LiteLLMAdminError(response.status_code, detail)
        try:
            data = response.json()
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}


def _error_text(response: httpx.Response) -> str:
    """Текст ошибки прокси без тела запроса (в нём мог быть ключ) — только `error.message`."""
    try:
        err = response.json().get("error")
    except (ValueError, AttributeError):
        return f"HTTP {response.status_code}"
    message = err.get("message") if isinstance(err, dict) else None
    return str(message)[:200] if message else f"HTTP {response.status_code}"

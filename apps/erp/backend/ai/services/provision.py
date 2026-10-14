"""Виртуальный ключ ERP в LiteLLM: дневной бюджет и трейсы Langfuse на стороне шлюза.

ERP ходит в шлюз своим ключом (`LITELLM_API_KEY` = `ERP_LITELLM_API_KEY` из `.env`, его
генерирует `make env`). Эта функция регистрирует значение ключа в LiteLLM (мастер-ключом, один
раз на запуск стенда — сервис `erp-ai-gateway`, `manage.py ai_gateway_sync`) и держит его
настройки в соответствии с окружением:

- `max_budget` + `budget_duration: 1d` — жёсткий дневной бюджет ERP (тот же `AI_DAILY_BUDGET_USD`,
  сутки UTC); превышение шлюз отвечает `budget_exceeded` → код `AI_BUDGET_EXCEEDED`;
- `metadata.logging` — колбэк Langfuse ключа: каждый вызов ERP шлюз пишет трейсом в Langfuse
  (CRM пишет свои трейсы сам — её вызовы этим ключом не идут и не дублируются);
- `models` — только алиасы ERP и запасная модель (ключ ERP не зовёт модели CRM).

Идемпотентно: ключа нет — `/key/generate` с этим значением, есть — `/key/update`. Мастер-ключ
нужен только здесь и в ERP-процессах не живёт. В M3-CRM-11 тот же шаг делает консоль CRM
(бюджет ERP — `settings.budget.erp_daily_usd`), без `.env`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import NamedTuple

import httpx

from .gateway import FEATURE_ALIASES

logger = logging.getLogger(__name__)

KEY_ALIAS = "erp"
FALLBACK_ALIAS = "fallback-model"
ADMIN_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class LangfuseTarget:
    public_key: str
    secret_key: str
    host: str


@dataclass(frozen=True)
class KeySpec:
    key: str
    max_budget_usd: float | None
    langfuse: LangfuseTarget | None = None


class AdminResponse(NamedTuple):
    status_code: int
    payload: dict | None


def _admin_request(method: str, url: str, master_key: str, body: dict | None = None) -> AdminResponse:
    """HTTP к API управления LiteLLM. Единственная точка сети модуля — тесты подменяют её."""
    response = httpx.request(
        method, url, json=body, headers={"Authorization": f"Bearer {master_key}"}, timeout=ADMIN_TIMEOUT_S
    )
    try:
        payload = response.json()
    except ValueError:
        payload = None
    return AdminResponse(response.status_code, payload if isinstance(payload, dict) else None)


def allowed_models() -> list[str]:
    return sorted({*FEATURE_ALIASES.values(), FALLBACK_ALIAS})


def key_settings(spec: KeySpec) -> dict:
    """Тело `/key/generate` / `/key/update` без самого значения ключа."""
    metadata: dict = {"system": "erp"}
    if spec.langfuse is not None:
        metadata["logging"] = [
            {
                "callback_name": "langfuse",
                "callback_type": "success_and_failure",
                "callback_vars": {
                    "langfuse_public_key": spec.langfuse.public_key,
                    "langfuse_secret_key": spec.langfuse.secret_key,
                    "langfuse_host": spec.langfuse.host,
                },
            }
        ]
    return {
        "key_alias": KEY_ALIAS,
        "models": allowed_models(),
        "max_budget": spec.max_budget_usd,
        "budget_duration": "1d" if spec.max_budget_usd is not None else None,
        "metadata": metadata,
    }


def sync_erp_key(base_url: str, master_key: str, spec: KeySpec) -> str:
    """Создать или обновить ключ ERP. Возвращает `created` / `updated`; ошибка API — RuntimeError."""
    base = base_url.rstrip("/")
    info = _admin_request("GET", f"{base}/key/info?key={spec.key}", master_key)
    exists = info.status_code == 200 and bool((info.payload or {}).get("info"))
    body = {"key": spec.key, **key_settings(spec)}
    path, outcome = ("/key/update", "updated") if exists else ("/key/generate", "created")
    response = _admin_request("POST", f"{base}{path}", master_key, body)
    if response.status_code != 200:
        detail = (response.payload or {}).get("error") or response.payload
        raise RuntimeError(f"LiteLLM {path} → {response.status_code}: {str(detail)[:300]}")
    logger.info("ERP gateway key %s: budget=%s langfuse=%s", outcome, spec.max_budget_usd, spec.langfuse is not None)
    return outcome

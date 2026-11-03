"""Виртуальный ключ EDS в LiteLLM (EDS-REG; образец — `apps/erp/backend/ai/services/provision.py`).

EDS ходит в шлюз своим ключом (`EDS_LITELLM_API_KEY`, его генерирует `make env`). `python -m app ai-key-sync` (сервис
compose `eds-ai-gateway`, один раз на запуск) регистрирует значение ключа мастер-ключом и держит настройки:

- `max_budget` + `budget_duration: 1d` — жёсткий дневной бюджет EDS (`EDS_AI_DAILY_BUDGET_USD`, сутки UTC);
- `models` — только алиасы функций EDS и запасная модель (ключ EDS не зовёт модели CRM и ERP);
- `metadata.system = eds` — строки EDS на «Расходах» консоли.

Идемпотентно: ключа нет — `/key/generate`, есть — `/key/update`. Мастер-ключ (`LITELLM_MASTER_KEY`) нужен только здесь,
в процессах api и worker его нет. Нет ключа EDS или мастер-ключа — пропуск с кодом 0 (помощник выключен).
"""

from typing import Any, Final

import httpx

from app.ai.gateway import FALLBACK_ALIAS, FUNCTION_ALIASES

KEY_ALIAS: Final = "eds"
TIMEOUT_S: Final = 30.0
# Транспорт HTTP: тесты подменяют `httpx.MockTransport`.
TRANSPORT: httpx.AsyncBaseTransport | None = None


def allowed_models() -> list[str]:
    return sorted({*FUNCTION_ALIASES.values(), FALLBACK_ALIAS})


def key_settings(max_budget_usd: float | None) -> dict[str, Any]:
    """Тело `/key/generate` и `/key/update` без самого значения ключа."""
    return {
        "key_alias": KEY_ALIAS,
        "models": allowed_models(),
        "max_budget": max_budget_usd,
        "budget_duration": "1d" if max_budget_usd is not None else None,
        "metadata": {"system": "eds"},
    }


async def sync_key(base_url: str, master_key: str, key: str, max_budget_usd: float | None) -> str:
    """Создать или обновить ключ EDS: `created` / `updated`; ошибка API — RuntimeError (без значения ключа)."""
    base = base_url.rstrip("/")
    async with httpx.AsyncClient(transport=TRANSPORT, timeout=TIMEOUT_S) as client:
        # Есть ли ключ — спрашиваем им самим: значение не попадает в адрес запроса и журналы прокси.
        info = await client.get(f"{base}/key/info", headers={"Authorization": f"Bearer {key}"})
        exists = info.status_code == 200 and bool(_json(info).get("info"))
        path, outcome = ("/key/update", "updated") if exists else ("/key/generate", "created")
        response = await client.post(
            f"{base}{path}",
            json={"key": key, **key_settings(max_budget_usd)},
            headers={"Authorization": f"Bearer {master_key}"},
        )
    if response.status_code != 200:
        raise RuntimeError(f"LiteLLM {path} → {response.status_code}")
    return outcome


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}

"""`python -m app ai-key-sync` — регистрация виртуального ключа EDS в LiteLLM (сервис compose `eds-ai-gateway`).

Читает только своё окружение — без базы и секретов EDS (сервису не нужны ни БД, ни S3): `EDS_LITELLM_API_KEY`,
`LITELLM_BASE_URL`, `EDS_AI_DAILY_BUDGET_USD` и мастер-ключ `LITELLM_MASTER_KEY` (он есть только здесь). Нет ключа EDS
или мастер-ключа, шлюз не ответил — сообщение и код 0: стенд поднимается, помощник «Заполнить из файла» выключен.
"""

import os

import httpx
import structlog

from app.ai import provision

log = structlog.get_logger(__name__)


def _budget() -> float | None:
    raw = os.environ.get("EDS_AI_DAILY_BUDGET_USD", "1").strip()
    try:
        value = float(raw)
    except ValueError:
        return 1.0
    return value if value > 0 else None  # 0 — без лимита шлюза (как у ERP)


async def run() -> int:
    key = os.environ.get("EDS_LITELLM_API_KEY", "").strip()
    master = os.environ.get("LITELLM_MASTER_KEY", "").strip()
    base = os.environ.get("LITELLM_BASE_URL", "http://litellm:4000")
    if not key or not master:
        log.warning("ai.key_sync_skipped", reason="no_eds_key" if not key else "no_master_key")
        return 0
    try:
        outcome = await provision.sync_key(base, master, key, _budget())
    except (RuntimeError, OSError, httpx.HTTPError) as exc:
        log.warning("ai.key_sync_failed", error=str(exc))
        return 0
    log.info("ai.key_synced", outcome=outcome, budget_usd=_budget())
    return 0

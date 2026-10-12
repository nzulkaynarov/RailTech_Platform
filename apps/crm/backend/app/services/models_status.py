"""«Модели ИИ» (только чтение): роль → провайдер, модель, здоровье, расход за сутки; проверка.

Модели и провайдеры — из каталога LiteLLM (`/model/info`), ключи провайдеров сюда не попадают.
Здоровье — последнее состояние монитора (`system_alerts`, ключ `model:<alias>`).
Проверка — один минимальный платный запрос (1 токен или эмбеддинг слова) по нажатию админа.
"""

import time
from collections.abc import Mapping
from datetime import datetime
from typing import Final

from openai import APIError, AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.litellm import EMBED_ALIAS
from app.integrations.litellm_catalog import ModelEntry
from app.integrations.llm_usage import COST_HEADER, UsageEvent, UsageSink, parse_cost
from app.models.system import SystemAlert
from app.schemas.spend import ModelStatus, ModelTestResult

ALIASES: Final = ("dialog-model", "qualifier-model", "fallback-model", "embed-model", "judge-model")


def statuses(
    entries: Mapping[str, ModelEntry],
    alerts: Mapping[str, SystemAlert],
    today: Mapping[str, float],
) -> list[ModelStatus]:
    aliases = list(ALIASES) + sorted(set(entries) - set(ALIASES))
    out: list[ModelStatus] = []
    for alias in aliases:
        entry = entries.get(alias)
        alert = alerts.get(f"model:{alias}")
        health = "unknown" if alert is None else ("problem" if alert.active else "ok")
        out.append(
            ModelStatus(
                alias=alias,
                provider=entry.provider if entry else None,
                model=entry.model if entry else None,
                health=health,
                health_detail=alert.detail if alert is not None and alert.active else None,
                checked_at=alert.updated_at if alert is not None else None,
                today_usd=round(today.get(alias, 0.0), 4),
            )
        )
    return out


async def probe(client: AsyncOpenAI, alias: str, usage: UsageSink | None) -> ModelTestResult:
    """Один минимальный запрос мимо резерва LiteLLM (`disable_fallbacks`): сбой виден честно."""
    started = time.monotonic()
    try:
        if alias == EMBED_ALIAS:
            raw_e = await client.embeddings.with_raw_response.create(model=alias, input=["ping"])
            model, tokens_in, tokens_out = _embed_usage(raw_e.parse())
            cost = parse_cost(raw_e.headers.get(COST_HEADER))
        else:
            raw_c = await client.chat.completions.with_raw_response.create(
                model=alias,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                extra_body={"disable_fallbacks": True},
            )
            model, tokens_in, tokens_out = _chat_usage(raw_c.parse())
            cost = parse_cost(raw_c.headers.get(COST_HEADER))
    except APIError as exc:
        detail = f"{getattr(exc, 'status_code', '') or type(exc).__name__}: {exc.message}"[:200]
        return ModelTestResult(
            alias=alias, ok=False, detail=detail, latency_ms=_ms(started), cost_usd=None
        )
    if usage is not None:
        await usage.record(UsageEvent("probe", alias, model, tokens_in, tokens_out, cost))
    return ModelTestResult(
        alias=alias, ok=True, detail=None, latency_ms=_ms(started), cost_usd=cost
    )


def _chat_usage(response: object) -> tuple[str | None, int, int]:
    usage = getattr(response, "usage", None)
    return (
        getattr(response, "model", None),
        getattr(usage, "prompt_tokens", 0) or 0,
        getattr(usage, "completion_tokens", 0) or 0,
    )


def _embed_usage(response: object) -> tuple[str | None, int, int]:
    usage = getattr(response, "usage", None)
    return getattr(response, "model", None), getattr(usage, "prompt_tokens", 0) or 0, 0


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


async def record_probe(
    session: AsyncSession, alias: str, ok: bool, detail: str | None, now: datetime
) -> None:
    """Результат «Проверить» — в состояние монитора (`system_alerts`, `model:<alias>`).

    Тогда «Состояние системы», чек-лист и «Модели ИИ» показывают одно и то же. `sent_at`
    не трогаем: о новом сбое в канал по-прежнему сообщает монитор.
    """
    key = f"model:{alias}"
    row = await session.get(SystemAlert, key)
    if row is None:
        row = SystemAlert(key=key, active=False)
        session.add(row)
    if ok:
        if row.active:
            row.active, row.resolved_at, row.first_seen_at, row.sent_at = False, now, None, None
        row.detail = None
    else:
        if not row.active:
            row.active, row.first_seen_at, row.sent_at, row.resolved_at = True, now, None, None
        row.detail = detail
    row.updated_at = now

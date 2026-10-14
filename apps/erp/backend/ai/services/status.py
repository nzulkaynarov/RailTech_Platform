"""Состояние ИИ ERP для консоли администратора CRM (ORCHESTRATOR §3.13, отдача — M3-ERP-06).

`ai_status()` отвечает без вызова моделей (ни одного платного запроса): включён ли ИИ, жив ли
шлюз (`/health/liveliness`), сколько потрачено сегодня и какой бюджет (журнал `ai.AICall` и
бюджет виртуального ключа ERP из `/key/info`), сколько задач и ошибок, последние ошибки,
алиасы и версии промптов. Сейчас читается командой `manage.py ai_status`; интеграционный
эндпоинт для центра внешних сервисов CRM — M3-ERP-06 (контракт сначала).
"""

from __future__ import annotations

import logging
from datetime import timedelta

import httpx
from django.conf import settings
from django.db.models import Count, Q, Sum
from django.utils import timezone

from .budget import daily_budget_usd
from .gateway import FEATURE_ALIASES
from .prompts import available_prompts, load_prompt

logger = logging.getLogger(__name__)

PROBE_TIMEOUT_S = 3.0
RECENT_ERRORS = 5


def _get(path: str, *, auth: bool) -> httpx.Response | None:
    headers = {"Authorization": f"Bearer {settings.LITELLM_API_KEY}"} if auth else {}
    try:
        return httpx.get(f"{settings.LITELLM_BASE_URL}{path}", headers=headers, timeout=PROBE_TIMEOUT_S)
    except httpx.HTTPError as exc:
        logger.info("AI status probe %s failed: %s", path, exc)
        return None


def gateway_status() -> dict:
    configured = bool(getattr(settings, "LITELLM_BASE_URL", "") and getattr(settings, "LITELLM_API_KEY", ""))
    if not configured:
        return {"configured": False, "reachable": None, "key": None}
    probe = _get("/health/liveliness", auth=False)
    reachable = probe is not None and probe.status_code == 200
    return {"configured": True, "reachable": reachable, "key": _key_info() if reachable else None}


def _key_info() -> dict | None:
    """Бюджет ключа ERP в шлюзе. Мастер-ключ (режим без виртуального ключа) своей записи не имеет."""
    response = _get("/key/info", auth=True)
    if response is None or response.status_code != 200:
        return None
    try:
        info = (response.json() or {}).get("info") or {}
    except ValueError:
        return None
    return {
        "alias": info.get("key_alias"),
        "spend_usd": info.get("spend"),
        "max_budget_usd": info.get("max_budget"),
        "budget_duration": info.get("budget_duration"),
        "budget_reset_at": info.get("budget_reset_at"),
        "langfuse": any(
            item.get("callback_name") == "langfuse" for item in (info.get("metadata") or {}).get("logging") or []
        ),
    }


def today_usage() -> dict:
    from ai.models import AICall, AIJob

    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    calls = AICall.objects.filter(created_at__gte=start)
    totals = calls.aggregate(
        calls=Count("id"),
        errors=Count("id", filter=~Q(status="ok")),
        spend=Sum("cost_usd"),
        input_tokens=Sum("input_tokens"),
        output_tokens=Sum("output_tokens"),
    )
    budget = daily_budget_usd()
    recent = AICall.objects.filter(created_at__gte=start - timedelta(days=1)).exclude(status="ok")[:RECENT_ERRORS]
    return {
        "date": timezone.localdate().isoformat(),
        "calls": totals["calls"],
        "errors": totals["errors"],
        "input_tokens": totals["input_tokens"] or 0,
        "output_tokens": totals["output_tokens"] or 0,
        "spend_usd": str(totals["spend"] or 0),
        "budget_usd": str(budget) if budget is not None else None,
        "jobs": AIJob.objects.filter(created_at__gte=start).count(),
        "recent_errors": [
            {"at": row.created_at.isoformat(), "feature": row.feature, "status": row.status, "code": row.error_code}
            for row in recent
        ],
    }


def ai_status() -> dict:
    cap = int(getattr(settings, "AI_DAILY_JOB_CAP_PER_COMPANY", 0) or 0)
    return {
        "system": "erp",
        "enabled": bool(getattr(settings, "AI_IMPORT_ENABLED", False)),
        "gateway": gateway_status(),
        "today": today_usage(),
        "job_cap_per_company": cap if cap > 0 else None,
        "aliases": dict(FEATURE_ALIASES),
        "prompts": {name: load_prompt(name).version for name in available_prompts()},
    }

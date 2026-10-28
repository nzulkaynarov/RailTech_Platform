"""Внешние сервисы ERP для `GET /health` integration (M3-ERP-06, ORCHESTRATOR §3.13; контракт `Health.externals`).

Источник данных — только то, что ERP уже пишет, и ни одного обращения к самим сервисам (ответ быстрый, < 300 мс):
- почты нет: письма ERP отправляет почтовый сервис CRM (W18A-P1), строка «Почта» — одна на ансамбль, в CRM;
- модели — журнал вызовов шлюза `ai.AICall`;
- курсы ЦБ, ТН ВЭД, S3 — лёгкие отметки в кэше (`core.external_status`), которые ставят места настоящих вызовов;
- Sentry — только настройка (доставка событий из ERP не наблюдаема).

Статус считает `derive_status` — чистая функция: правила описаны в контракте (`ExternalService.status`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from django.conf import settings
from django.db.models import Max
from django.utils import timezone

from core import external_status as ext

logger = logging.getLogger(__name__)

#: Плановые задачи: давно не было успеха — «degraded». Курсы — раз в сутки, ТН ВЭД — раз в неделю.
CBU_STALE_AFTER = timedelta(days=3)
TNVED_STALE_AFTER = timedelta(days=14)
#: Статусы вызова шлюза, при которых сам шлюз ответил (качество ответа модели — не сбой сервиса).
AI_SERVED = ("ok", "refusal", "truncated", "invalid_json")
AI_FAILED = "error"


@dataclass(frozen=True)
class Facts:
    configured: bool
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None
    ok_24h: int = 0
    errors_24h: int = 0
    stale_after: timedelta | None = None


def derive_status(facts: Facts, *, enabled: bool, now: datetime) -> str:
    """ok / degraded / fail / unknown / disabled по правилам контракта."""
    if not enabled or not facts.configured:
        return "disabled"
    ok, err = facts.last_success_at, facts.last_error_at
    if ok is None and err is None:
        return "unknown"
    if err is not None and (ok is None or err > ok):
        return "degraded" if facts.ok_24h > 0 else "fail"
    if facts.stale_after is not None and ok is not None and now - ok > facts.stale_after:
        return "degraded"
    return "ok"


# ── Сбор фактов по сервисам ─────────────────────────────────────────────────────────────────────────


def _from_marks(code: str, *, configured: bool, now: datetime, stale_after: timedelta | None = None) -> Facts:
    last_ok, last_err, text = ext.last_marks(code)
    ok, err = ext.counts(code, now=now)
    return Facts(configured, last_ok, last_err, text, ok, err, stale_after if last_ok is not None else None)


def _cbu_rates(now: datetime) -> Facts:
    facts = _from_marks("cbu_rates", configured=True, now=now, stale_after=CBU_STALE_AFTER)
    if facts.last_success_at is None and facts.last_error_at is None:
        from core.models import ExchangeRate

        newest = ExchangeRate.objects.filter(source="CBU").aggregate(at=Max("created_at"))["at"]
        if newest is not None:  # кэш пуст (Redis потерян): последняя загруженная строка курса — нижняя оценка успеха
            return Facts(True, newest, None, None, 0, 0, None)
    return facts


def _customs_tariff(now: datetime) -> Facts:
    facts = _from_marks("customs_tariff", configured=True, now=now, stale_after=TNVED_STALE_AFTER)
    if facts.last_success_at is None and facts.last_error_at is None:
        from catalog.models import HSCode
        from master_data.tnved import TNVED_SOURCE

        newest = HSCode.objects.filter(source=TNVED_SOURCE).aggregate(at=Max("updated_at"))["at"]
        if newest is not None:
            return Facts(True, newest, None, None, 0, 0, None)
    return facts


def _litellm_configured() -> bool:
    return bool(
        getattr(settings, "AI_IMPORT_ENABLED", False)
        and getattr(settings, "LITELLM_BASE_URL", "")
        and getattr(settings, "LITELLM_API_KEY", "")
    )


def _litellm(now: datetime) -> Facts:
    from ai.models import AICall

    since = ext.window_start(now)
    served = AICall.objects.filter(status__in=AI_SERVED)
    failed = AICall.objects.filter(status=AI_FAILED)
    last_ok = served.order_by("-created_at").values_list("created_at", flat=True).first()
    last_err = failed.order_by("-created_at").values_list("created_at", "error_code").first()
    return Facts(
        _litellm_configured(),
        last_ok,
        last_err[0] if last_err else None,
        ext.short_error(last_err[1] or "AI_GATEWAY_ERROR") if last_err else None,
        served.filter(created_at__gte=since).count(),
        failed.filter(created_at__gte=since).count(),
    )


def _s3(now: datetime) -> Facts:
    return _from_marks("s3", configured=bool(getattr(settings, "MINIO_ENDPOINT", "")), now=now)


def _sentry(now: datetime) -> Facts:
    # Доставка событий в Sentry из ERP не наблюдаема: сообщаем только «настроен». Нет DSN — «disabled».
    configured = bool(getattr(settings, "SENTRY_DSN", ""))
    return Facts(configured, ok_24h=0, errors_24h=0, last_success_at=None)


_BUILDERS: dict[str, Callable[[datetime], Facts]] = {
    "cbu_rates": _cbu_rates,
    "customs_tariff": _customs_tariff,
    "litellm": _litellm,
    "s3": _s3,
    "sentry": _sentry,
}
assert set(_BUILDERS) == set(ext.REPORTED_CODES), "каждому показываемому коду нужен сборщик фактов"


def _iso(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment else None


def build_externals(now: datetime | None = None) -> list[dict]:
    """`Health.externals`: по записи на сервис в порядке `core.external_status.REPORTED_CODES`. Сбой сборки одного сервиса —
    он `unknown`, остальные и сам `/health` не страдают."""
    now = now or timezone.now()
    rows: list[dict] = []
    for code in ext.REPORTED_CODES:
        enabled = ext.is_enabled(code)
        try:
            facts = _BUILDERS[code](now)
            status = derive_status(facts, enabled=enabled, now=now)
            # Sentry «настроен» = «ok»: данных об исходах нет, но и проблем не видно.
            if code == "sentry" and status != "disabled":
                status = "ok"
        except Exception:  # noqa: BLE001 — сборка статуса сервиса не должна ронять /health
            logger.exception("externals: cannot build status for %s", code)
            facts, status = Facts(configured=True), "unknown"
        rows.append(
            {
                "code": code,
                "status": status,
                "enabled": enabled,
                "switchable": code in ext.SWITCHABLE,
                "last_success_at": _iso(facts.last_success_at),
                "last_error_at": _iso(facts.last_error_at),
                "last_error": facts.last_error,
                "ok_24h": facts.ok_24h,
                "errors_24h": facts.errors_24h,
            }
        )
    return rows

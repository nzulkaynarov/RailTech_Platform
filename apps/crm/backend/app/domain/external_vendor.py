"""Здоровье вендоров моделей по журналу шлюза (M3-CRM-12, ADR-0024): без вызова моделей.

Источник — строки `/spend/logs/v2` LiteLLM (проверено на v1.105.0): `custom_llm_provider` — вендор,
обслуживший вызов; `status` `success|failure`; `startTime`/`endTime` — задержка; `spend` — USD;
`model_group` — обслуживший алиас; `metadata.original_model_group` — запрошенный (переход на
запасную модель по `router_settings.fallbacks`); `metadata.error_information` — класс и текст
ошибки.
Бюджет вендора — `GET /provider/budgets` (`provider_budget_config` шлюза). Чистые функции.
"""

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Final

from app.domain.ai_spend import parse_tags
from app.domain.external_registry import Status, vendor_key
from app.domain.external_status import CheckResult, Metric

MIN_CALLS: Final = 3
FAIL_SHARE: Final = 0.5
WARN_SHARE: Final = 0.2
BUDGET_WARN: Final = 0.8
_AUTH_CLASSES: Final = frozenset({"AuthenticationError", "PermissionDeniedError"})
_QUOTA_CLASSES: Final = frozenset({"RateLimitError", "BudgetExceededError"})
_KEYLIKE: Final = re.compile(r"(sk|key|AIza)[-_A-Za-z0-9]{6,}")


@dataclass(frozen=True, slots=True)
class CallRow:
    vendor: str | None
    at: datetime
    latency_ms: int | None
    failed: bool
    cost_usd: float
    diverted_from: str | None = None
    error: str | None = None
    error_kind: str | None = None


def scrub(text: str) -> str:
    """Текст ошибки провайдера без фрагментов ключей (некоторые провайдеры их повторяют)."""
    return _KEYLIKE.sub("***", text)[:200]


def to_call(raw: Mapping[str, object], providers: Mapping[str, str | None]) -> CallRow | None:
    at = _time(raw.get("startTime"))
    if at is None:
        return None
    end = _time(raw.get("endTime"))
    meta_raw = raw.get("metadata")
    meta: Mapping[str, object] = meta_raw if isinstance(meta_raw, dict) else {}
    tags_raw = raw.get("request_tags")
    tags = parse_tags(tags_raw if isinstance(tags_raw, list) else [])
    served = _text(raw.get("model_group"))
    original = _text(meta.get("original_model_group")) or tags.get("model")
    vendor = _text(raw.get("custom_llm_provider")) or providers.get(served or "") or None
    failed = _text(raw.get("status")) == "failure"
    diverted = providers.get(original) if original and served and original != served else None
    error, kind = _error(meta.get("error_information")) if failed else (None, None)
    spend = raw.get("spend")
    return CallRow(
        vendor=vendor,
        at=at,
        latency_ms=int((end - at).total_seconds() * 1000) if end is not None else None,
        failed=failed,
        cost_usd=float(spend) if isinstance(spend, int | float) else 0.0,
        diverted_from=diverted,
        error=error,
        error_kind=kind,
    )


def _error(info: object) -> tuple[str | None, str | None]:
    if not isinstance(info, dict):
        return None, None
    cls = _text(info.get("error_class"))
    code = _text(info.get("error_code"))
    message = _text(info.get("error_message"))
    kind = "other"
    if cls in _AUTH_CLASSES or code in ("401", "403"):
        kind = "auth"
    elif cls in _QUOTA_CLASSES or code == "429":
        kind = "quota"
    text = " ".join(p for p in (code, cls, message) if p)
    return (scrub(text) if text else None), kind


@dataclass(slots=True)
class VendorStats:
    calls: int = 0
    failures: int = 0
    cost_usd: float = 0.0
    diverted: int = 0
    latencies: list[int] = field(default_factory=list)
    last_error: str | None = None
    last_error_kind: str | None = None
    last_error_at: datetime | None = None
    last_success_at: datetime | None = None


def stats(rows: Iterable[CallRow], since: datetime) -> dict[str, VendorStats]:
    """Вызовы с `since` по вендорам; вызовы, ушедшие с вендора на запасную модель, — `diverted`."""
    out: dict[str, VendorStats] = {}
    for row in sorted(rows, key=lambda r: r.at):
        if row.at < since:
            continue
        if row.diverted_from and row.diverted_from != row.vendor:
            out.setdefault(row.diverted_from, VendorStats()).diverted += 1
        if not row.vendor:
            continue
        s = out.setdefault(row.vendor, VendorStats())
        s.calls += 1
        s.cost_usd += row.cost_usd
        if row.latency_ms is not None and not row.failed:
            s.latencies.append(row.latency_ms)
        if row.failed:
            s.failures += 1
            s.last_error, s.last_error_kind, s.last_error_at = row.error, row.error_kind, row.at
        else:
            s.last_success_at = row.at
    return out


def p95(values: list[int]) -> int | None:
    """95-й процентиль по ближайшему рангу; пусто — None."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, -(-95 * len(ordered) // 100))
    return ordered[rank - 1]


def day_metrics(s: VendorStats | None) -> dict[str, Metric]:
    s = s or VendorStats()
    return {
        "calls_24h": s.calls,
        "failures_24h": s.failures,
        "error_rate_24h": round(s.failures / s.calls, 4) if s.calls else None,
        "p95_ms_24h": p95(s.latencies),
        "spend_24h_usd": round(s.cost_usd, 6),
        "fallback_24h": s.diverted,
    }


@dataclass(frozen=True, slots=True)
class VendorFacts:
    vendor: str
    logs_available: bool
    window: VendorStats | None = None
    budget_spend: float | None = None
    budget_limit: float | None = None
    day: Mapping[str, Metric] = field(default_factory=dict)
    disabled: bool = False


_HINTS: Final = {
    "auth": "Ключ провайдера отклонён — введите новый ключ в «Модели ИИ»",
    "quota": "У провайдера кончились кредиты или квота — пополните баланс в его консоли",
    "other": (
        "Сбой на стороне провайдера: бот переходит на запасную модель. Если сбой затянулся — "
        "выключите провайдера здесь, вызовы пойдут на запасную модель"
    ),
}


def vendor(f: VendorFacts) -> CheckResult:
    key = vendor_key(f.vendor)
    w = f.window or VendorStats()
    metrics: dict[str, Metric] = {
        "calls_15m": w.calls,
        "failures_15m": w.failures,
        "budget_spend_usd": f.budget_spend,
        "budget_limit_usd": f.budget_limit,
        **f.day,
    }
    if f.disabled:
        summary = "Выключен вручную — вызовы этого провайдера идут на запасную модель"
        return CheckResult(key, "off", summary, metrics=metrics)
    if not f.logs_available:
        return CheckResult(
            key,
            "unknown",
            "Журнал вызовов шлюза недоступен — состояние провайдера неизвестно",
            hint="Проверьте строку «Шлюз моделей (LiteLLM)»",
            metrics=metrics,
        )
    share = w.failures / w.calls if w.calls else 0.0
    used = _budget_share(f)
    if used is not None and used >= 1:
        return CheckResult(
            key,
            "fail",
            "Дневной потолок расходов провайдера в шлюзе исчерпан — запросы отклоняются",
            error=f"{f.budget_spend:.2f} из {f.budget_limit:.2f} USD",
            hint="Посмотрите, что тратит, в «Расходах»; потолок сбросится через сутки",
            metrics=metrics,
        )
    auth_now = bool(w.failures) and w.last_error_kind == "auth" and _last_is_error(w)
    if auth_now or (w.calls >= MIN_CALLS and share >= FAIL_SHARE):
        return _failing(key, w, "fail", metrics)
    if w.failures and (share >= WARN_SHARE or _last_is_error(w)):
        return _failing(key, w, "warn", metrics)
    if used is not None and used >= BUDGET_WARN:
        return CheckResult(
            key,
            "warn",
            f"Израсходовано {used:.0%} дневного потолка провайдера",
            hint="Посмотрите, что тратит, в «Расходах»",
            metrics=metrics,
        )
    summary = f"{w.calls} вызовов за 15 мин без ошибок" if w.calls else "Вызовов за 15 мин не было"
    if w.failures:
        summary = f"{w.calls} вызовов за 15 мин, ошибок {w.failures}"
    return CheckResult(key, "ok", summary, metrics=metrics)


def _failing(key: str, w: VendorStats, status: Status, metrics: dict[str, Metric]) -> CheckResult:
    kind = w.last_error_kind or "other"
    return CheckResult(
        key,
        status,
        f"Провайдер отвечает ошибками: {w.failures} из {w.calls} вызовов за 15 мин",
        error=w.last_error,
        hint=_HINTS.get(kind, _HINTS["other"]),
        metrics=metrics,
    )


def _last_is_error(w: VendorStats) -> bool:
    if w.last_error_at is None:
        return False
    return w.last_success_at is None or w.last_success_at < w.last_error_at


def _budget_share(f: VendorFacts) -> float | None:
    if not f.budget_limit or f.budget_spend is None:
        return None
    return f.budget_spend / f.budget_limit


def _text(raw: object) -> str:
    return raw.strip() if isinstance(raw, str) else ""


def _time(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo is not None else None

"""Расходы на ИИ по ансамблю (M3-CRM-09, ARCHITECTURE §8): теги вызова и агрегация журнала LiteLLM.

Чистые функции без I/O. Источник истины — журнал расходов LiteLLM (`LiteLLM_SpendLogs`, по строке
на вызов): каждая система ансамбля помечает вызов тегами `system=crm|erp`, `feature=<функция>`,
`model=<алиас>` (`metadata.tags` тела запроса → колонка `request_tags`). Здесь — разбор строки
журнала и свёртка «день × система × функция × модель»: вызовы, токены, USD, деградации.

Деградация — успешный вызов, обслуженный запасной моделью (`model_group == fallback-model`):
и BudgetGuard CRM, и `router_settings.fallbacks` LiteLLM (у них тег `model` — исходный алиас,
`model_group` — фактический). Проверки моделей (`feature=probe`) деградацией не считаются.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

Group = Literal["day", "system", "feature", "model"]

SYSTEMS: Final = ("crm", "erp")
# Вызов без тега системы/функции (чужой клиент шлюза, ручной curl, служебный вызов прокси).
UNTAGGED: Final = "other"
FALLBACK_ALIAS: Final = "fallback-model"
NOT_DEGRADATION: Final = frozenset({"probe"})
MAX_PERIOD_DAYS: Final = 90
TAG_KEYS: Final = ("system", "feature", "model")


def call_tags(system: str, feature: str, alias: str) -> list[str]:
    """Теги вызова для журнала LiteLLM: канон `ключ=значение` (ERP пишет так же, M1-ERP-06)."""
    return [f"system={system}", f"feature={feature}", f"model={alias}"]


def parse_tags(tags: Iterable[object]) -> dict[str, str]:
    """`system`/`feature`/`model` из `request_tags`; чужие теги (User-Agent и т. п.) игнорируются.

    Принимается и `ключ:значение` — на случай клиента, который пишет теги через двоеточие.
    """
    out: dict[str, str] = {}
    for tag in tags:
        if not isinstance(tag, str):
            continue
        for sep in ("=", ":"):
            key, found, value = tag.partition(sep)
            key, value = key.strip().lower(), value.strip()
            if found and key in TAG_KEYS and value and key not in out:
                out[key] = value
                break
    return out


@dataclass(frozen=True, slots=True)
class LogRow:
    """Строка журнала расходов LiteLLM, приведённая к измерениям экрана «Расходы»."""

    request_id: str
    at: datetime
    cost_usd: float
    input_tokens: int
    output_tokens: int
    system: str
    feature: str
    model: str
    failed: bool
    degraded: bool


def to_row(raw: Mapping[str, object]) -> LogRow | None:
    """Строка `/spend/logs/v2` → `LogRow`; без `request_id`/`startTime` — None (не наш формат)."""
    request_id = raw.get("request_id")
    at = _parse_time(raw.get("startTime"))
    if not isinstance(request_id, str) or not request_id or at is None:
        return None
    tags = parse_tags(_tags(raw.get("request_tags")))
    served = _text(raw.get("model_group"))
    model = served or tags.get("model") or _text(raw.get("model")) or UNTAGGED
    failed = _text(raw.get("status")) == "failure"
    feature = tags.get("feature", UNTAGGED)
    return LogRow(
        request_id=request_id,
        at=at,
        cost_usd=_number(raw.get("spend")),
        input_tokens=int(_number(raw.get("prompt_tokens"))),
        output_tokens=int(_number(raw.get("completion_tokens"))),
        system=tags.get("system", UNTAGGED).lower(),
        feature=feature,
        model=model,
        failed=failed,
        degraded=served == FALLBACK_ALIAS and not failed and feature not in NOT_DEGRADATION,
    )


@dataclass(slots=True)
class Agg:
    calls: int = 0
    failed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    fallback_calls: int = 0

    def add(self, other: "Agg | LogRow") -> None:
        if isinstance(other, LogRow):
            self.calls += 1
            self.failed_calls += int(other.failed)
            self.fallback_calls += int(other.degraded)
        else:
            self.calls += other.calls
            self.failed_calls += other.failed_calls
            self.fallback_calls += other.fallback_calls
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cost_usd += other.cost_usd


@dataclass(frozen=True, slots=True)
class Cell:
    day: date
    system: str
    feature: str
    model: str


@dataclass(frozen=True, slots=True)
class Cube:
    """Свёртка журнала за период: ячейки «день × система × функция × модель»."""

    first: date
    last: date
    cells: Mapping[Cell, Agg] = field(default_factory=dict)

    def days(self) -> list[date]:
        return [self.first + timedelta(days=n) for n in range((self.last - self.first).days + 1)]


def window(first: date, last: date, tz: str) -> tuple[datetime, datetime]:
    """Сутки `first`…`last` по часовому поясу CRM → полуинтервал [начало, конец) в UTC."""
    zone = ZoneInfo(tz)
    start = datetime.combine(first, time.min, zone).astimezone(UTC)
    end = datetime.combine(last + timedelta(days=1), time.min, zone).astimezone(UTC)
    return start, end


def build_cube(rows: Iterable[LogRow], first: date, last: date, tz: str) -> Cube:
    """Ячейки за период; повтор строки (перекрытие окон выборки) учитывается один раз."""
    zone = ZoneInfo(tz)
    start, end = window(first, last, tz)
    seen: set[str] = set()
    cells: dict[Cell, Agg] = defaultdict(Agg)
    for row in rows:
        if row.request_id in seen or not start <= row.at < end:
            continue
        seen.add(row.request_id)
        day = row.at.astimezone(zone).date()
        cells[Cell(day, row.system, row.feature, row.model)].add(row)
    return Cube(first, last, dict(cells))


def group(cube: Cube, by: Group) -> list[tuple[str, Agg, dict[str, Agg]]]:
    """Ряды по измерению: (ключ, итог, по системам). По дням — каждый день периода, и пустой.

    Остальные измерения — по убыванию стоимости, затем по ключу (порядок стабилен).
    """
    totals: dict[str, Agg] = defaultdict(Agg)
    systems: dict[str, dict[str, Agg]] = defaultdict(lambda: defaultdict(Agg))
    for cell, agg in cube.cells.items():
        key = cell.day.isoformat() if by == "day" else getattr(cell, by)
        totals[key].add(agg)
        systems[key][cell.system].add(agg)
    if by == "day":
        keys = [d.isoformat() for d in cube.days()]
    else:
        keys = sorted(totals, key=lambda k: (-totals[k].cost_usd, k))
    return [(k, totals.get(k, Agg()), dict(systems.get(k, {}))) for k in keys]


def combine(aggs: Iterable[Agg]) -> Agg:
    out = Agg()
    for agg in aggs:
        out.add(agg)
    return out


def total(cube: Cube) -> Agg:
    return combine(cube.cells.values())


def by_system_day(cube: Cube) -> dict[str, dict[date, Agg]]:
    out: dict[str, dict[date, Agg]] = defaultdict(lambda: defaultdict(Agg))
    for cell, agg in cube.cells.items():
        out[cell.system][cell.day].add(agg)
    return out


def over_budget(spent: float, daily_usd: float) -> bool:
    """Как мягкий бюджет CRM (`domain/budget`): ≥ 100 % лимита; лимит 0 — без лимита."""
    return daily_usd > 0 and spent >= daily_usd


def systems_order(present: Iterable[str]) -> list[str]:
    """CRM и ERP — всегда (пустая ERP = «не подключена»), прочие — по алфавиту, `other` в конце."""
    rest = sorted(set(present) - set(SYSTEMS) - {UNTAGGED})
    tail = [UNTAGGED] if UNTAGGED in set(present) else []
    return [*SYSTEMS, *rest, *tail]


def period_error(first: date, last: date, today: date) -> str | None:
    """Почему период нельзя показать (None — можно): порядок дат, длина, будущее."""
    if first > last:
        return "from_after_to"
    if (last - first).days + 1 > MAX_PERIOD_DAYS:
        return "too_long"
    if last > today:
        return "future"
    return None


def _tags(raw: object) -> Sequence[object]:
    return raw if isinstance(raw, list | tuple) else ()


def _text(raw: object) -> str:
    return raw.strip() if isinstance(raw, str) else ""


def _number(raw: object) -> float:
    if isinstance(raw, bool):
        return 0.0
    if isinstance(raw, int | float):
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return 0.0
    return 0.0


def _parse_time(raw: object) -> datetime | None:
    """`startTime` журнала: ISO с `+00:00` (v1.105.0) или без зоны — тогда это UTC."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

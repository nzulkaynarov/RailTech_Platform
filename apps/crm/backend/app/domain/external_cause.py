"""Причина, кто исправляет и действие по внешним сервисам; группировка по корню (W15-H3, ADR-0024).

Чистые функции. Код решает, интерфейс только показывает (ORCHESTRATOR §3 п. 5):

- `diagnose` — результат проверки сервиса → состояние словом (`State`), причина (`cause_key`),
  «кто исправляет» (`Owner`) и одно главное действие (`Action`) плюс запасные;
- `build_groups` — строки с общей причиной сворачиваются в одну («Ключ Anthropic отклонён — не
  работают: диалог с клиентом, запасная модель, поиск по базе знаний»);
- `recheck_due` — затухание повторных проверок сломанного (1, 2, 5, 7 мин, дальше каждые 7 мин);
- `plan_alerts` — одно «сломано» после 15 минут и одно «восстановлено» на причину (дедупликация по
  `cause_key`; состояние хранит БД, поэтому рестарт процесса её не обнуляет).

«Ожидаемо на стенде»: стенд ансамбля (`APP_ENV=dev`, `Settings.is_stand`; у прода `prod`, у тестов
`test`) и причина, которую на стенде чинить некому (ключи, оплата, сервер, «не настроено»).
Такие строки серые, без оповещений.
"""

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

from app.domain.external_incidents import AlertText, duration_text
from app.domain.external_registry import (
    ALIAS_FUNCTIONS,
    VENDOR_TITLES,
    ServiceSpec,
    Status,
    vendor_aliases,
)
from app.domain.external_status import CheckResult
from app.domain.system_status import hosting_ask
from app.security.log_mask import mask_secrets

State = Literal[
    "ok",
    "broken",
    "unstable",
    "degraded",
    "not_configured",
    "disabled",
    "expected",
    "not_checked",
]
Owner = Literal["admin", "owner", "hosting", "provider"]
Action = Literal[
    "enter_key",
    "enter_token",
    "recheck",
    "reconnect",
    "open_settings",
    "write_owner",
    "write_hosting",
    "disable_provider",
    "open_bus",
]

#: «Сломано» — только непрерывный `fail` не короче этого срока (от начала полосы); короче —
#: «Нестабильно».
ALERT_AFTER: Final = timedelta(minutes=15)
#: «Восстановлено» — только после непрерывного `ok` не короче этого срока.
RECOVERY_AFTER: Final = timedelta(minutes=5)
#: Последняя строка оповещения; рассылка заменяет её ссылкой на «Подключения» Платформы (B-009).
OPEN_LINE: Final = "Открыть: Платформа → Admin → Подключения."
#: Не больше одного «Сломано» на причину за это время; повторные провалы — сводка, не серия.
ALERT_COOLDOWN: Final = timedelta(hours=24)
#: Дребезг: столько провалов (полос `fail`) за `FLAP_WINDOW` — «Нестабильно», даже если сейчас `ok`.
#: Короткий провал между двумя `ok` с таким промежутком не сбрасывает отсчёт восстановления.
BLIP_GAP: Final = timedelta(minutes=3)
FLAP_MIN: Final = 3
FLAP_WINDOW: Final = timedelta(hours=3)
#: Затухание повторных проверок сломанного, мин: после 1-го, 2-го, 3-го, 4-го и далее подряд сбоя.
#: Проверки сбоя с 0-й минуты идут на 0, 1, 3, 8 и 15-й: 4 провала за 8 минут — ещё не «Сломано».
BACKOFF_MINUTES: Final = (1, 2, 5, 7)
BACKOFF_SLACK: Final = timedelta(seconds=10)
TECHNICAL_LIMIT: Final = 600
_SEVERITY: Final[dict[State, int]] = {
    "broken": 0,
    "unstable": 1,
    "degraded": 2,
    "not_configured": 3,
    "not_checked": 4,
    "expected": 5,
    "disabled": 6,
    "ok": 7,
}
#: Причины «ещё не подключено»: слово «Не настроено», а не «Сломано».
NOT_CONFIGURED: Final = frozenset({"no_token", "not_configured", "erp_not_connected"})
#: Причины «так задумано»: выключено намеренно (настройкой сервера или вручную).
INTENTIONAL: Final = frozenset({"intentional", "disabled_manual"})
#: Причины, у которых корень общий для нескольких сервисов: ключ группы — по области, не по сервису.
SHARED_SCOPE: Final = {"erp_not_connected": "erp"}
OWNER_LABEL: Final[dict[Owner, str]] = {
    "admin": "администратор",
    "owner": "владелец компании (ключ и оплата провайдера)",
    "hosting": "хостинг (сервер)",
    "provider": "провайдер (сбой на его стороне, ждём)",
}


@dataclass(frozen=True, slots=True)
class Route:
    owner: Owner | None
    action: Action | None
    more: tuple[Action, ...] = ()


_HOSTING: Final = Route("hosting", "write_hosting", ("recheck",))
_ADMIN_FIX: Final = Route("admin", "reconnect", ("recheck",))
ROUTES: Final[dict[str, Route]] = {
    "key_rejected": Route("owner", "enter_key", ("write_owner", "disable_provider")),
    "quota": Route("owner", "write_owner", ("disable_provider", "recheck")),
    "budget_cap": Route("owner", "write_owner", ("recheck",)),
    "budget_near": Route("owner", "write_owner"),
    "provider_errors": Route("provider", "recheck", ("disable_provider",)),
    "no_token": Route("admin", "enter_token"),
    "token_rejected": Route("admin", "enter_token", ("write_owner",)),
    "network": _HOSTING,
    "webhook_config": Route("hosting", "write_hosting"),
    "webhook_info": Route("provider", "recheck"),
    "webhook_state": _ADMIN_FIX,
    "webhook_delivery": _HOSTING,
    "backlog": _HOSTING,
    "server_down": _HOSTING,
    "gateway_db": _HOSTING,
    "langfuse_keys": _HOSTING,
    "not_configured": Route("admin", "open_settings"),
    "smtp_auth_failed": _ADMIN_FIX,
    "smtp_tls_failed": _ADMIN_FIX,
    "smtp_invalid_host": _ADMIN_FIX,
    "smtp_rejected": _ADMIN_FIX,
    "smtp_unavailable": Route("provider", "recheck", ("reconnect",)),
    "queue_stuck": _HOSTING,
    "last_failed": Route("admin", "recheck", ("open_settings",)),
    "backup_admin": Route("admin", "open_settings", ("recheck",)),
    "cert": _HOSTING,
    "cert_expiring": _HOSTING,
    "erp_not_connected": Route("admin", "reconnect"),
    "erp_sync_failed": _ADMIN_FIX,
    "erp_handoff_failed": _ADMIN_FIX,
    "erp_events_failed": _ADMIN_FIX,
    # Недоставленное на шине (кроме ERP, у него своя строка): журнал обмена открывает админ.
    "bus_dlq": Route("admin", "open_bus", ("recheck",)),
    # Права EDS не ушли на шину (B-005): проверка повторяет публикацию сама, шину чинит хостинг.
    "eds_rights": _HOSTING,
    "checks_stale": _HOSTING,
    "ai_unavailable": Route("admin", "recheck", ("open_settings",)),
    "flapping": Route(None, "recheck"),
    "intentional": Route(None, None),
    "disabled_manual": Route(None, None),
}
#: Сервисы ERP (`erp.<код>`): кто исправляет зависит от сервиса.
ERP_EXTERNAL_ROUTES: Final[dict[str, Route]] = {
    "erp.cbu_rates": Route("provider", "recheck"),
    "erp.customs_tariff": Route("provider", "recheck"),
    "erp.litellm": Route("owner", "write_owner", ("recheck",)),
    "erp.s3": _HOSTING,
    "erp.sentry": Route("hosting", "write_hosting"),
}
_NEED: Final = {
    "key_rejected": "выпустить новый ключ API у провайдера и передать его администратору Платформы",
    "quota": "пополнить баланс или поднять квоту у провайдера",
    "budget_cap": "решить, поднимать ли дневной потолок расходов провайдера",
    "budget_near": "решить, поднимать ли дневной потолок расходов провайдера",
}


@dataclass(frozen=True, slots=True)
class Context:
    """Всё, что `diagnose` нужно кроме результата проверки."""

    stand: bool = False
    disabled: bool = False
    never_checked: bool = False
    stale: bool = False
    providers: Mapping[str, str | None] = field(default_factory=dict)
    # Сколько `fail` идёт подряд; `None` — полосы нет (или неизвестно): считается «непрерывно».
    fail_for: timedelta | None = None
    # Провалов (полос `fail`) за сутки и за `FLAP_WINDOW` — для «Нестабильно».
    flaps_24h: int = 0
    flaps_recent: int = 0


@dataclass(frozen=True, slots=True)
class Diagnosis:
    key: str
    title: str
    status: Status
    state: State
    cause: str | None
    cause_key: str
    owner: Owner | None
    action: Action | None
    more: tuple[Action, ...]
    headline: str
    detail: str | None
    affected: tuple[str, ...]
    technical: str | None
    since: datetime | None = None
    flaps_24h: int = 0


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    state: State
    owner: Owner | None
    action: Action | None
    more: tuple[Action, ...]
    headline: str
    detail: str | None
    affected: tuple[str, ...]
    service_keys: tuple[str, ...]
    titles: tuple[str, ...]
    since: datetime | None
    technical: tuple[str, ...]
    message: str | None
    flaps_24h: int = 0


def vendor_title(provider: str) -> str:
    """«Anthropic» вместо «Anthropic (Claude)» — короткое имя для заголовков строк."""
    return VENDOR_TITLES.get(provider, provider).split(" (")[0]


def route_of(spec: ServiceSpec, cause: str | None) -> Route:
    if cause == "erp_external":
        return ERP_EXTERNAL_ROUTES.get(spec.key, _HOSTING)
    if cause is not None and cause in ROUTES:
        return ROUTES[cause]
    if spec.fix_path:
        return Route("admin", "open_settings", ("recheck",))
    return _HOSTING


def cause_key_of(spec_key: str, cause: str | None, state: State) -> str:
    if cause == "checks_stale":
        # Фоновые проверки не идут (воркер или периодика): одна причина на все устаревшие сервисы.
        return "worker:checks_stale"
    if state in ("not_checked", "disabled", "ok"):
        return f"{spec_key}:{'disabled' if state == 'disabled' else state}"
    scope = SHARED_SCOPE.get(cause or "", spec_key)
    return f"{scope}:{cause or 'status'}"


def _state_of(status: Status, cause: str | None, ctx: Context) -> State:
    if ctx.disabled or cause == "disabled_manual":
        return "disabled"
    if ctx.never_checked or ctx.stale or status == "unknown":
        return "not_checked"
    if status == "ok":
        return "unstable" if ctx.flaps_recent >= FLAP_MIN else "ok"
    if cause in INTENTIONAL:
        return "disabled"
    if cause in NOT_CONFIGURED or status == "off":
        return "not_configured"
    if status == "fail":
        sustained = ctx.fail_for is None or ctx.fail_for >= ALERT_AFTER
        return "broken" if sustained else "unstable"
    return "degraded"


def _headline(
    spec: ServiceSpec, result: CheckResult, cause: str | None, state: State, flaps: int = 0
) -> str:
    if cause == "flapping":
        return f"{spec.title}: нестабильная связь, провалов за сутки: {flaps}"
    if spec.vendor is not None and state in ("broken", "unstable", "degraded"):
        name = vendor_title(spec.vendor)
        lines = {
            "key_rejected": f"Ключ {name} отклонён",
            "quota": f"У {name} кончились кредиты или квота",
            "budget_cap": f"Дневной потолок расходов {name} исчерпан",
            "budget_near": f"Почти исчерпан дневной потолок расходов {name}",
            "provider_errors": f"{name} отвечает ошибками",
        }
        if cause in lines:
            return lines[cause]
    return result.summary


def _affected(spec: ServiceSpec, providers: Mapping[str, str | None]) -> tuple[str, ...]:
    if spec.vendor is None:
        return ()
    aliases = vendor_aliases(providers).get(spec.vendor, [])
    return tuple(ALIAS_FUNCTIONS.get(a, a) for a in aliases)


def technical_text(error: str | None) -> str | None:
    """Сырой ответ провайдера для «Технических подробностей»: без секретов и не длиннее предела."""
    if not error or not error.strip():
        return None
    return mask_secrets(error.strip())[:TECHNICAL_LIMIT]


def diagnose(
    spec: ServiceSpec, result: CheckResult, ctx: Context, since: datetime | None = None
) -> Diagnosis:
    cause = "checks_stale" if ctx.stale else result.cause
    state = _state_of(result.status, cause, ctx)
    if state == "unstable" and result.status == "ok":
        cause = "flapping"
    route = (
        route_of(spec, cause)
        if state in ("broken", "unstable", "degraded", "not_configured")
        else None
    )
    owner = route.owner if route else None
    action: Action | None = route.action if route else None
    more = route.more if route else ()
    if state == "not_checked":
        owner = "hosting" if ctx.stale else None
        action, more = "recheck", ("write_hosting",) if ctx.stale else ()
    if state == "disabled":
        owner, action, more = None, None, ()
    on_stand = ctx.stand and state in ("broken", "unstable", "degraded", "not_configured")
    if on_stand and (state == "not_configured" or owner in ("hosting", "owner")):
        state, action, more = "expected", "recheck", ()
    return Diagnosis(
        key=spec.key,
        title=spec.title,
        status=result.status,
        state=state,
        cause=cause,
        cause_key=cause_key_of(spec.key, cause, state if state != "expected" else "broken"),
        owner=owner,
        action=action,
        more=more,
        headline=_headline(spec, result, cause, state, ctx.flaps_24h),
        detail=result.hint,
        affected=_affected(spec, ctx.providers) if state != "ok" else (),
        technical=technical_text(result.error),
        since=since,
        flaps_24h=ctx.flaps_24h,
    )


def _local(moment: datetime, tz: str) -> str:
    return moment.astimezone(ZoneInfo(tz)).strftime("%d.%m %H:%M")


def owner_message(
    group: Group, cause: str | None, tz: str, company: str = "Платформе"
) -> str | None:
    """Готовый текст «Написать владельцу / передать хостингу»; отправляет пользователь, не мы."""
    if group.owner not in ("owner", "hosting"):
        return None
    head = group.headline
    lines = ["Здравствуйте!", f"В {company} сбой: {head}."]
    if group.affected:
        lines.append(f"Не работают: {', '.join(group.affected)}.")
    if group.since is not None:
        lines.append(f"Началось: {_local(group.since, tz)}.")
    need = _NEED.get(cause or "") or hosting_ask(group.detail) or group.detail
    if need:
        lines.append(f"Что нужно: {need}.")
    return "\n".join(lines)


def build_groups(
    items: Iterable[Diagnosis], tz: str = "UTC", company: str = "Платформе"
) -> list[Group]:
    """Свернуть диагнозы без состояния `ok` по корню: одна причина — одна группа."""
    order: dict[str, list[Diagnosis]] = {}
    for d in items:
        if d.state == "ok":
            continue
        order.setdefault(d.cause_key, []).append(d)
    groups = [_group(cause_key, members, tz, company) for cause_key, members in order.items()]
    groups.sort(key=lambda g: _SEVERITY[g.state])
    return groups


def _group(cause_key: str, members: Sequence[Diagnosis], tz: str, company: str) -> Group:
    first = min(members, key=lambda d: _SEVERITY[d.state])
    since = min((d.since for d in members if d.since is not None), default=None)
    affected: list[str] = []
    for d in members:
        affected.extend(a for a in d.affected if a not in affected)
    technical = tuple(
        dict.fromkeys(
            f"{d.title}: {d.technical}" if len(members) > 1 else d.technical
            for d in members
            if d.technical
        )
    )
    group = Group(
        id=cause_key,
        state=first.state,
        owner=first.owner,
        action=first.action,
        more=first.more,
        headline=first.headline,
        detail=first.detail,
        affected=tuple(affected),
        service_keys=tuple(d.key for d in members),
        titles=tuple(d.title for d in members),
        since=since,
        technical=technical,
        message=None,
        flaps_24h=max(d.flaps_24h for d in members),
    )
    message = owner_message(group, first.cause, tz, company) if first.state == "broken" else None
    return replace(group, message=message)


def since_for(
    status: Status,
    *,
    fail_since: datetime | None,
    unhealthy_since: datetime | None,
    incident_started: datetime | None,
) -> datetime | None:
    """«С {время}»: у `fail` — начало полосы `fail`; у остальных не-`ok` — первая не-`ok` проверка.

    Сервис, который дни был «не настроен» (`off`) или с перебоями (`warn`), а потом упал, «сломан» с
    момента падения, а не с первой не-`ok` проверки: от него же считаются 15 минут до оповещения.
    """
    if status == "fail":
        return fail_since or incident_started or unhealthy_since
    return unhealthy_since


# --- затухание повторных проверок ---------------------------------------------------------------


#: Причины, которые сами не проходят (ключ, пароль, квота): проверка не чаще раза в 15 минут, чтобы
#: неудачными входами не блокировать ящик у провайдера почты и не долбить провайдера.
SLOW_CAUSES: Final = frozenset(
    {
        "key_rejected",
        "quota",
        "budget_cap",
        "token_rejected",
        "smtp_auth_failed",
        "smtp_tls_failed",
        "smtp_invalid_host",
        "smtp_rejected",
    }
)
SLOW_RECHECK: Final = timedelta(minutes=15)


def recheck_interval(consecutive_failures: int, cause: str | None = None) -> timedelta:
    """Через сколько перепроверять сломанное: 1, 2, 5, 7 мин по номеру сбоя подряд, дальше 7."""
    if cause in SLOW_CAUSES:
        return SLOW_RECHECK
    n = max(1, consecutive_failures)
    return timedelta(minutes=BACKOFF_MINUTES[min(n, len(BACKOFF_MINUTES)) - 1])


def recheck_due(
    consecutive_failures: int, last_checked_at: datetime, now: datetime, cause: str | None = None
) -> bool:
    return now - last_checked_at + BACKOFF_SLACK >= recheck_interval(consecutive_failures, cause)


def ok_run_start(
    rows: Sequence[tuple[str, datetime]], blip: timedelta = BLIP_GAP
) -> datetime | None:
    """Начало текущей непрерывной полосы `ok` по проверкам сервиса (новые первыми).

    Короткий провал или `warn` между двумя `ok` с промежутком не больше `blip` отсчёт не сбрасывает
    (дребезг не должен отодвигать «Восстановлено»); дольше — полоса начинается заново. Сейчас не
    `ok` или проверок нет — `None`.
    """
    if not rows or rows[0][0] != "ok":
        return None
    start = rows[0][1]
    i, n = 0, len(rows)
    while i < n:
        if rows[i][0] == "ok":
            start = rows[i][1]
            i += 1
            continue
        j = i
        while j < n and rows[j][0] != "ok":
            j += 1
        if j >= n or rows[i - 1][1] - rows[j][1] > blip:
            break
        i = j
    return start


# --- оповещения: одно «сломано» и одно «восстановлено» на причину ---------------------------------


@dataclass(frozen=True, slots=True)
class OpenCause:
    cause_key: str
    started_at: datetime
    alerted_at: datetime | None
    service_keys: tuple[str, ...]
    suppressed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Step:
    kind: Literal["open", "alert", "suppress", "restore", "close"]
    cause_key: str
    started_at: datetime | None = None


def plan_alerts(
    groups: Iterable[Group],
    open_causes: Mapping[str, OpenCause],
    states: Mapping[str, State],
    now: datetime,
    ok_since: Mapping[str, datetime] | None = None,
    recently_alerted: Collection[str] = (),
) -> list[Step]:
    """Что сделать с журналом причин и оповещениями после очередного прохода проверок.

    `open`: «Сломано» (непрерывный `fail` ≥ 15 мин) — завести запись, начало — начало полосы;
    короткие провалы и «Нестабильно» записей не заводят и не оповещают;
    `alert`: о причине ещё не сообщали — одно «Сломано»;
    `suppress`: о причине уже сообщали за последние сутки — сводка «нестабильно» вместо новой серии;
    `restore`: все сервисы причины непрерывно `ok` не меньше 5 мин — закрыть запись (начало `ok` —
    `started_at` шага) и, если сообщали о сбое, сообщить о возврате;
    `close`: причина исчезла иначе (выключили, «ожидаемо», сменилась) — закрыть молча.
    «Не проверено», «нестабильно» и «перебои» запись не трогают: данных для вывода нет.
    """
    since_ok = ok_since or {}
    broken = {g.id: g for g in groups if g.state == "broken"}
    steps: list[Step] = []
    for cause_key, group in broken.items():
        row = open_causes.get(cause_key)
        started = row.started_at if row else (group.since or now)
        if now - started < ALERT_AFTER:
            continue
        if row is None:
            steps.append(Step("open", cause_key, started))
        if row is None or row.alerted_at is None:
            if cause_key not in recently_alerted:
                # Сутки с прошлого «Сломано» прошли, а сбой всё ещё непрерывный: одно сообщение
                # со сводкой повторов (в том числе после подавления), а не молчание и не серия.
                steps.append(Step("alert", cause_key, started))
            elif row is None or row.suppressed_at is None:
                steps.append(Step("suppress", cause_key, started))
    for cause_key, row in open_causes.items():
        if cause_key in broken:
            continue
        members = [states.get(k) for k in row.service_keys]
        if members and all(m == "ok" for m in members):
            recovered = [since_ok.get(k) for k in row.service_keys]
            if all(t is not None and now - t >= RECOVERY_AFTER for t in recovered):
                at = max(t for t in recovered if t is not None)
                steps.append(Step("restore", cause_key, at))
        elif any(m in ("not_checked", "degraded", "unstable") for m in members):
            continue
        else:
            steps.append(Step("close", cause_key))
    return steps


def broken_alert(
    group: Group,
    since: datetime,
    now: datetime,
    tz: str,
    repeats: int = 0,
    since_previous: timedelta | None = None,
) -> AlertText:
    """`repeats` — сколько раз причина срабатывала с прошлого «Сломано» (с ним и текущим):
    больше одного — сводка «Нестабилен: N провалов» вместо серии сообщений."""
    lines = [f"С {_local(since, tz)} (уже {duration_text(now - since)})."]
    if repeats > 1 and since_previous is not None:
        lines.append(
            f"Нестабилен: {repeats} {_plural(repeats)} с прошлого сообщения "
            f"({duration_text(since_previous)} назад)."
        )
    elif group.flaps_24h > 1:
        lines.append(f"За сутки это уже {group.flaps_24h}-й провал: связь нестабильна.")
    if group.affected:
        lines.append(f"Не работают: {', '.join(group.affected)}.")
    if group.owner == "owner" and group.action == "enter_key":
        lines.append(
            "Кто исправляет: администратор вводит новый ключ; ключ и оплата — у владельца."
        )
    elif group.owner is not None:
        lines.append(f"Кто исправляет: {OWNER_LABEL[group.owner]}.")
    if group.detail:
        lines.append(f"Что сделать: {group.detail}")
    lines.append(OPEN_LINE)
    return AlertText(f"⚠️ Сломано: {group.headline}", tuple(lines))


def _plural(n: int) -> str:
    """«2 провала», «5 провалов», «21 провал»."""
    if n % 10 == 1 and n % 100 != 11:
        return "провал"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "провала"
    return "провалов"


def restored_alert(headline: str, lasted: timedelta) -> AlertText:
    return AlertText(
        f"✅ Восстановлено: {headline}",
        (f"Не работало {duration_text(lasted)}.", OPEN_LINE),
    )

"""Экран «Состояние системы» (аудит 2026-10-12 §3 п. 6): факты → статус и понятная причина.

Чистые функции: сервис собирает факты (готовность зависимостей, строки `system_alerts`,
очередь, конфигурация), здесь — только правила «ok / warn / fail / unknown» и тексты.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal
from urllib.parse import urlsplit

from app.domain.alerts import QUEUE_LIMIT
from app.domain.public_urls import is_local_url

Status = Literal["ok", "warn", "fail", "unknown"]
STALLED_MINUTES: Final = 15
#: Компоненты, чей сбой на тестовом стенде ожидаем: нет секретов сервера, локальный адрес CRM.
STAND_EXPECTED: Final = frozenset({"secrets", "crm_url", "bot", "channel"})
HOSTING_WHO: Final = "Это настраивает тот, кто разворачивал Платформу (хостинг)"


def hosting_hint(what: str, ask: str) -> str:
    """«Что случилось. Кто исправляет (хостинг). Что ему передать» (W15-H3)."""
    return f"{what}. {HOSTING_WHO}. Отправьте ему: «{ask}»"


def hosting_ask(hint: str | None) -> str | None:
    """Что передать хостингу — из текста `hosting_hint`; нет такой фразы — None."""
    if not hint or HOSTING_WHO not in hint:
        return None
    _, _, tail = hint.partition("Отправьте ему: «")
    return tail.removesuffix("»") or None


_DEPENDENCIES: Final = {
    "database": ("База данных", "PostgreSQL недоступен — CRM и бот не работают"),
    "s3": ("Хранилище файлов", "S3 (RustFS) недоступно — документы и вложения не сохраняются"),
    "litellm": ("Шлюз моделей", "LiteLLM недоступен — бот не отвечает клиентам"),
}


@dataclass(frozen=True, slots=True)
class Component:
    key: str
    title: str
    status: Status
    reason: str
    checked_at: datetime | None


@dataclass(frozen=True, slots=True)
class AlertRow:
    """Строка `system_alerts`, как её оставил монитор."""

    key: str
    active: bool
    detail: str | None
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class QueueFacts:
    waiting: int
    stalled: int
    failed_last_hour: int


@dataclass(frozen=True, slots=True)
class BotFacts:
    """Что известно о боте со слов процесса `crm-bot` (`bot_runtime`, S0-4): без значений токена."""

    running: bool
    source: str
    last_error: str | None


@dataclass(frozen=True, slots=True)
class BackupFacts:
    """Состояние тома бэкапов и демона (`services/backups.py`)."""

    mounted: bool
    daemon_alive: bool
    last_success: datetime | None
    requested_at: datetime | None
    # Файл heartbeat хоть раз появлялся: демон бэкапа на этом сервере развёрнут.
    daemon_seen: bool = True
    # Откуда факты: `volume` — том backup-контейнера (dev), `rustfs` — бакет `backups`, куда
    # пишет VPS 2 (прод, M5-CRM-01). Для `rustfs` демона и флага «сделать сейчас» нет.
    source: str = "volume"
    # Код ошибки чтения бакета (`bucket_missing`, `access_denied`, `unreachable`) и техдеталь.
    error: str | None = None
    error_detail: str | None = None
    # База → время её последней копии (None — копии нет); только для `rustfs`.
    databases: Mapping[str, datetime | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AiBudgetFacts:
    """Расход ИИ сегодня по системе из журнала LiteLLM (M3-CRM-09); лимит 0 — без лимита."""

    system: str
    spent_usd: float
    daily_usd: float


@dataclass(frozen=True, slots=True)
class ErpExternal:
    """Внешний сервис ERP из `Health.externals[]` (M3-ERP-06): как его описала сама ERP."""

    code: str
    status: (
        str  # ok | degraded | fail | unknown | disabled (чужое значение читатель сводит к unknown)
    )
    enabled: bool
    switchable: bool
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    ok_24h: int
    errors_24h: int


@dataclass(frozen=True, slots=True)
class ErpFacts:
    """Итог последней проверки коннектора ERP (`services/erp_connector.py`, кэш 30 с)."""

    configured: bool
    status: str | None = None
    version: str | None = None
    migrations_applied: bool | None = None
    queue_alive: bool | None = None
    checked_at: datetime | None = None
    latency_ms: int | None = None
    # Класс ошибки пробы (`integrations/erp.ErpErrorKind`); None — ответ получен.
    error: str | None = None
    detail: str | None = None
    # Внешние сервисы ERP: None — ERP не передала поле (версия до M3-ERP-06), () — передала пустой.
    externals: tuple[ErpExternal, ...] | None = None


STALE_BACKUP_HOURS = 26
DAEMON_SILENT_AFTER: Final = timedelta(minutes=2)
REQUEST_UNANSWERED_AFTER: Final = timedelta(minutes=2)
ROLE_TITLES: Final = {
    "dialog-model": "Диалог",
    "qualifier-model": "Квалификатор",
    "fallback-model": "Резерв",
    "embed-model": "Поиск",
    "judge-model": "Проверка качества",
}
_ORDER: Final = ("fail", "warn", "unknown", "ok")
_LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})  # noqa: S104


def dependencies(checks: Mapping[str, bool], now: datetime) -> list[Component]:
    result = []
    for key, (title, problem) in _DEPENDENCIES.items():
        if key not in checks:
            continue
        ok = checks[key]
        result.append(Component(key, title, "ok" if ok else "fail", "" if ok else problem, now))
    return result


def models(alerts: Sequence[AlertRow]) -> list[Component]:
    """Модели — по последней проверке монитора (раз в час); сами здесь не вызываются."""
    rows = sorted((a for a in alerts if a.key.startswith("model:")), key=lambda a: a.key)
    if not rows:
        return [
            Component(
                "models",
                "Модели ИИ",
                "unknown",
                "Монитор ещё не проверял модели — проверка раз в час, в начале часа",
                None,
            )
        ]
    return [
        Component(
            a.key,
            f"Модель ИИ: {role_title(a.key.split(':', 1)[1])}",
            "fail" if a.active else "ok",
            _model_reason(a.detail) if a.active else "",
            a.updated_at,
        )
        for a in rows
    ]


def role_title(alias: str) -> str:
    return ROLE_TITLES.get(alias, alias)


def _model_reason(detail: str | None) -> str:
    base = detail or "проблема у провайдера"
    return f"{base}. Проверьте баланс и ключ у провайдера («Модели ИИ» → «Проверить»)"


def ordered(components: Sequence[Component]) -> list[Component]:
    """Сначала сбои, затем предупреждения и неизвестное, исправное — в конце (порядок стабилен)."""
    return sorted(components, key=lambda c: _ORDER.index(c.status))


def budget(alerts: Sequence[AlertRow], now: datetime) -> Component:
    row = next((a for a in alerts if a.key == "budget"), None)
    if row is not None and row.active:
        return Component("budget", "Бюджет моделей", "warn", row.detail or "", row.updated_at)
    return Component("budget", "Бюджет моделей", "ok", "", row.updated_at if row else now)


# Бот живёт в отдельном процессе `crm-bot` (S0-4): если он не отчитывается, статус бота неизвестен.
BOT_PROCESS_ERRORS = {
    "bot_process_never_started": hosting_hint(
        "Процесс бота ещё ни разу не запускался на сервере", "Запустить crm-bot вместе с ансамблем"
    ),
    "bot_process_down": hosting_hint(
        "Процесс бота на сервере не отвечает", "Перезапустить crm-bot и посмотреть его журнал"
    ),
}


def bot(facts: BotFacts | None, mode: str, now: datetime) -> Component:
    """Бот «работает» только если polling-задача жива; причина — из супервизора, не догадка."""
    title = "Telegram-бот"
    if mode == "disabled":
        return Component("bot", title, "fail", "Бот выключен настройкой сервера", now)
    if facts is not None and facts.last_error in BOT_PROCESS_ERRORS:
        return Component("bot", title, "fail", BOT_PROCESS_ERRORS[facts.last_error], now)
    if facts is None or facts.source == "none":
        reason = "Токен бота не задан — «Подключения» → «Telegram-бот»"
        return Component("bot", title, "fail", reason, now)
    if not facts.running:
        return Component("bot", title, "fail", _bot_failure(facts.last_error), now)
    return Component("bot", title, "ok", "принимает сообщения", now)


def _bot_failure(error: str | None) -> str:
    """Причина остановки бота словами: класс исключения aiogram админу ничего не говорит."""
    text = (error or "").lower()
    if "network" in text or "timeout" in text:
        return "Нет связи с Telegram — проверьте интернет на сервере; бот переподключится сам"
    if "unauthorized" in text:
        return "Telegram не принимает токен бота — введите новый в «Подключениях»"
    if "conflict" in text:
        return "Этот токен уже использует другой сервер — остановите второй стенд или смените токен"
    return "Бот не принимает сообщения — проверьте токен в «Подключениях»"


def crm_url_problem(url: str) -> str | None:
    """Почему ссылки на CRM в Telegram не откроются у менеджеров; None — адрес в порядке."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if not host:
        return "Адрес CRM не указан"
    if host in _LOCAL_HOSTS or host.endswith(".localhost"):
        return "Адрес CRM указывает на этот компьютер — ссылки из Telegram не откроются у команды"
    if parts.scheme != "https":
        return "Адрес CRM без https — ссылки откроются без защищённого соединения"
    return None


@dataclass(frozen=True, slots=True)
class PlatformUrlFacts:
    """Адрес Платформы из окружения (`PLATFORM_PUBLIC_URL` / `PLATFORM_DOMAIN`) и режим стенда."""

    url: str | None
    prod: bool


_PLATFORM_HOSTING: Final = "Это настраивает хостинг: PLATFORM_DOMAIN в .env сервера"


def platform_url_problem(facts: PlatformUrlFacts) -> str | None:
    """Почему ссылка «Вход» в письмах сотрудникам не откроется; None — адрес годится."""
    if not facts.url:
        return (
            "Адрес Платформы не задан — приглашения по почте не уходят, а ссылки из Telegram "
            f"ведут в старую CRM. {_PLATFORM_HOSTING}"
        )
    if facts.prod and is_local_url(facts.url):
        return (
            "Адрес Платформы указывает на localhost — ссылка «Вход» в письмах сотрудникам "
            f"не откроется. {_PLATFORM_HOSTING}"
        )
    return None


def crm_url(url: str, now: datetime, platform: PlatformUrlFacts | None = None) -> Component:
    """Адреса для ссылок: Платформа (письма и ссылки Telegram) и CRM («Настройки» → «Компания»).

    Ссылки из Telegram ведут в Платформу (B-009); адрес CRM нужен только как запасной, пока адреса
    Платформы нет, поэтому его неполадки показываются лишь тогда."""
    title = "Адреса для ссылок"
    problems: list[str] = []
    crm_problem = crm_url_problem(url)
    platform_used = platform is not None and bool(platform.url)
    if crm_problem is not None and not platform_used:
        problems.append(f"{crm_problem} — укажите адрес CRM в «Настройки» → «Компания»")
    platform_problem = platform_url_problem(platform) if platform is not None else None
    if platform_problem is not None:
        problems.append(platform_problem)
    if problems:
        return Component("crm_url", title, "warn", ". ".join(problems), now)
    shown = [url, *([platform.url] if platform is not None and platform.url else [])]
    return Component("crm_url", title, "ok", " · ".join(shown), now)


def channel(channel_id: int | None, now: datetime) -> Component:
    if channel_id is None:
        return Component(
            "channel",
            "Канал команды",
            "warn",
            "Канал не подключён — «Подключения» → «Канал команды»; передачи менеджерам не приходят",
            now,
        )
    return Component("channel", "Канал команды", "ok", "", now)


def queue(facts: QueueFacts, now: datetime) -> Component:
    problems = []
    if facts.stalled:
        problems.append(f"{facts.stalled} задач выполняются дольше {STALLED_MINUTES} минут")
    if facts.waiting > QUEUE_LIMIT:
        problems.append(f"{facts.waiting} задач в ожидании (порог {QUEUE_LIMIT})")
    if facts.failed_last_hour:
        problems.append(f"{facts.failed_last_hour} задач упали за последний час")
    status: Status = "warn" if problems else "ok"
    reason = "; ".join(problems) if problems else f"в ожидании: {facts.waiting}"
    return Component("queue", "Очередь задач", status, reason, now)


BACKUP_TITLE: Final = "Резервные копии"
_BACKUP_ERRORS: Final[dict[str, tuple[Status, str, str]]] = {
    "bucket_missing": (
        "fail",
        "Бакет резервных копий не найден в хранилище — статус копий неизвестен",
        "Создайте бакет «backups» в RustFS (S3_BUCKETS у сервиса s3-init) и проверьте "
        "BACKUP_RUSTFS_* у контейнера backup на сервере базы (VPS 2)",
    ),
    "access_denied": (
        "fail",
        "Нет доступа к бакету резервных копий — ключ S3 у CRM не принят",
        "Проверьте S3_ACCESS_KEY и S3_SECRET_KEY у crm-api и crm-worker: они должны совпадать "
        "с ключами RustFS",
    ),
    "unreachable": (
        "unknown",
        "Хранилище резервных копий недоступно — статус копий неизвестен",
        "Проверьте RustFS (карточка «Хранилище файлов») и сеть VPS 1; пока он недоступен, "
        "копии с VPS 2 не выгружаются",
    ),
}
_BACKUP_SERVER_HINT: Final = (
    "На сервере базы (VPS 2): docker logs rt-db-backup-1, затем infra/deploy/backup-now.sh; "
    "проверьте доступ VPS 2 к RustFS на VPS 1 (порт 9000) и BACKUP_RUSTFS_*"
)


def backup_hint(facts: BackupFacts) -> str | None:
    """«Что сделать» для сбоя бэкапа из бакета; для тома и для здорового бэкапа подсказки нет."""
    if facts.source != "rustfs":
        return None
    if facts.error is not None:
        return _BACKUP_ERRORS.get(facts.error, _BACKUP_ERRORS["unreachable"])[2]
    return _BACKUP_SERVER_HINT


def _rustfs_backup(now: datetime, facts: BackupFacts) -> Component:
    """Прод: бэкап делает VPS 2, CRM видит только бакет. Нет успешной копии за сутки — `fail`.

    `fail` открывает инцидент центра внешних сервисов (оповещение — с антиспамом, ADR-0024).
    Бакет недоступен по сети — `unknown`: инцидент не меняется, сбой RustFS виден в «Хранилище».
    """
    if facts.error is not None:
        status, reason, _ = _BACKUP_ERRORS.get(facts.error, _BACKUP_ERRORS["unreachable"])
        return Component("backup", BACKUP_TITLE, status, reason, now)
    missing = sorted(db for db, at in facts.databases.items() if at is None)
    if facts.last_success is None:
        if missing and len(missing) < len(facts.databases):
            reason = f"Нет копии баз: {', '.join(missing)} — «Резервные копии»"
        else:
            reason = "В бакете резервных копий нет ни одной полной копии — «Резервные копии»"
        return Component("backup", BACKUP_TITLE, "fail", reason, now)
    age_h = (now - facts.last_success).total_seconds() / 3600
    if age_h > STALE_BACKUP_HOURS:
        stale = sorted(
            db
            for db, at in facts.databases.items()
            if at is not None and (now - at).total_seconds() / 3600 > STALE_BACKUP_HOURS
        )
        which = f" (база {', '.join(stale)})" if stale and len(stale) < len(facts.databases) else ""
        reason = f"Нет успешной копии за сутки: последняя {int(age_h)} ч назад{which}"
        return Component("backup", BACKUP_TITLE, "fail", reason, now)
    return Component("backup", BACKUP_TITLE, "ok", f"Последняя копия {int(age_h)} ч назад", now)


def backup(now: datetime, facts: BackupFacts) -> Component:
    """Бэкапы (ADR-0013): демон жив по heartbeat, последняя копия не старше 26 ч.

    heartbeat не появлялся ни разу — демон не развёрнут (warn); был и устарел — fail.
    Источник `rustfs` (прод, M5-CRM-01) — отдельное правило: `_rustfs_backup`.
    """
    if facts.source == "rustfs":
        return _rustfs_backup(now, facts)
    name = BACKUP_TITLE
    if not facts.mounted:
        reason = hosting_hint(
            "Хранилище резервных копий не подключено к CRM",
            "Подключить хранилище резервных копий к CRM",
        )
        return Component("backup", name, "unknown", reason, now)
    if not facts.daemon_alive and not facts.daemon_seen:
        # Демона нет вовсе (dev, сервис не развёрнут) — предупреждение, а не авария.
        reason = "Резервное копирование не запущено на этом сервере"
        return Component("backup", name, "warn", reason, now)
    if not facts.daemon_alive:
        reason = hosting_hint(
            "Сервис резервного копирования не отвечает, копии не делаются",
            "Запустить сервис резервных копий (backup)",
        )
        return Component("backup", name, "fail", reason, now)
    if request_unanswered(now, facts):
        reason = "Запрошенная копия не началась — сервис резервного копирования не отвечает"
        return Component("backup", name, "warn", reason, now)
    if facts.last_success is None:
        return Component("backup", name, "fail", "Успешных копий нет — «Резервные копии»", now)
    age_h = (now - facts.last_success).total_seconds() / 3600
    if age_h > STALE_BACKUP_HOURS:
        reason = f"Последняя копия {int(age_h)} ч назад — сделайте копию в «Резервных копиях»"
        return Component("backup", name, "warn", reason, now)
    return Component("backup", name, "ok", f"Последняя копия {int(age_h)} ч назад", now)


def request_unanswered(now: datetime, facts: BackupFacts) -> bool:
    """«Сделать сейчас» висит дольше 2 мин без нового успеха — демон флаг не забрал."""
    asked = facts.requested_at
    if asked is None or now - asked <= REQUEST_UNANSWERED_AFTER:
        return False
    return facts.last_success is None or facts.last_success < asked


ERP_TITLE: Final = "ERP (бэк-офис)"
_ERP_ERRORS: Final = {
    "invalid_url": "Адрес ERP некорректен — исправьте в «Подключениях» → «ERP»",
    "unauthorized": "ERP не принимает сервисный токен — введите новый в «Подключениях» → «ERP»",
    "unavailable": "ERP не отвечает — проверьте адрес и доступность сервера ERP",
    "bad_response": "ERP ответила неожиданно — проверьте, что адрес ведёт на интеграционный API",
}


def erp(facts: ErpFacts, now: datetime) -> Component:
    """Коннектор не настроен — не ошибка (CRM автономна, ADR-0022); сбой связи — `fail`."""
    if not facts.configured:
        reason = "Коннектор ERP не настроен — «Подключения» → «ERP»; CRM работает автономно"
        return Component("erp", ERP_TITLE, "unknown", reason, now)
    if facts.error is not None:
        reason = _ERP_ERRORS.get(facts.error, _ERP_ERRORS["bad_response"])
        if facts.error == "unavailable" and facts.detail:
            reason = reason.replace(" — ", f" ({facts.detail}) — ", 1)
        return Component("erp", ERP_TITLE, "fail", reason, facts.checked_at or now)
    problems = []
    if facts.status == "degraded":
        problems.append("ERP сообщает о деградации")
    if facts.migrations_applied is False:
        problems.append("миграции ERP не применены")
    if facts.queue_alive is False:
        problems.append("очередь задач ERP не отвечает")
    version = f"версия {facts.version}" if facts.version else "версия неизвестна"
    if problems:
        return Component("erp", ERP_TITLE, "warn", f"{'; '.join(problems)} ({version})", now)
    return Component("erp", ERP_TITLE, "ok", f"{version}, миграции применены, очередь жива", now)


def secrets(missing: Sequence[str], now: datetime, *, secrets_key: bool = True) -> Component:
    title = "Секреты сервера"
    if missing:
        names = ", ".join(missing)
        reason = hosting_hint(
            f"На сервере не заданы обязательные настройки: {names}",
            f"Задать в .env сервера: {names}",
        )
        return Component("secrets", title, "fail", reason, now)
    if not secrets_key:
        reason = "Не задан ключ шифрования (SECRETS_KEY) — токен бота нельзя сменить из интерфейса"
        return Component("secrets", title, "warn", reason, now)
    return Component("secrets", title, "ok", "все обязательные заданы", now)


AI_BUDGET_TITLE: Final = "Бюджет ИИ сегодня"
_SYSTEM_LABELS: Final = {"crm": "CRM", "erp": "ERP", "other": "без тега"}


def ai_budget(facts: Sequence[AiBudgetFacts] | None, now: datetime) -> Component:
    """«Бюджет ИИ сегодня: CRM x/y USD, ERP x/y USD» — из журнала шлюза; превышение — `warn`."""
    if facts is None:
        reason = "Журнал расходов шлюза моделей недоступен — расход по системам неизвестен"
        return Component("ai_budget", AI_BUDGET_TITLE, "unknown", reason, now)
    parts = [_ai_part(f) for f in facts if f.system != "other" or f.spent_usd > 0]
    over = [f for f in facts if f.daily_usd > 0 and f.spent_usd >= f.daily_usd]
    if over:
        names = ", ".join(_SYSTEM_LABELS.get(f.system, f.system) for f in over)
        reason = f"Бюджет превышен: {names}. {', '.join(parts)}"
        return Component("ai_budget", AI_BUDGET_TITLE, "warn", reason, now)
    return Component("ai_budget", AI_BUDGET_TITLE, "ok", ", ".join(parts), now)


def _ai_part(f: AiBudgetFacts) -> str:
    label = _SYSTEM_LABELS.get(f.system, f.system)
    if f.daily_usd > 0:
        return f"{label} {f.spent_usd:.2f}/{f.daily_usd:.2f} USD"
    return f"{label} {f.spent_usd:.2f} USD (без лимита)"

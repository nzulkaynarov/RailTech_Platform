"""Экран «Состояние системы» (аудит 2026-10-12 §3 п. 6): факты → статус и понятная причина.

Чистые функции: сервис собирает факты (готовность зависимостей, строки `system_alerts`,
очередь, конфигурация), здесь — только правила «ok / warn / fail / unknown» и тексты.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal
from urllib.parse import urlsplit

from app.domain.alerts import QUEUE_LIMIT

Status = Literal["ok", "warn", "fail", "unknown"]
STALLED_MINUTES: Final = 15

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
    """Что известно о боте в процессе api (`BotSupervisor`): без значений токена."""

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


def bot(facts: BotFacts | None, mode: str, now: datetime) -> Component:
    """Бот «работает» только если polling-задача жива; причина — из супервизора, не догадка."""
    title = "Telegram-бот"
    if mode == "disabled":
        return Component("bot", title, "fail", "Бот выключен настройкой сервера", now)
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


def crm_url(url: str, now: datetime) -> Component:
    problem = crm_url_problem(url)
    title = "Адрес CRM"
    if problem is None:
        return Component("crm_url", title, "ok", url, now)
    return Component("crm_url", title, "warn", f"{problem} — «Настройки» → «Компания»", now)


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


def backup(now: datetime, facts: BackupFacts) -> Component:
    """Бэкапы (ADR-0013): демон жив по heartbeat, последняя копия не старше 26 ч.

    heartbeat не появлялся ни разу — демон не развёрнут (warn); был и устарел — fail.
    """
    name = "Резервные копии"
    if not facts.mounted:
        reason = "Хранилище резервных копий не подключено — обратитесь к администратору сервера"
        return Component("backup", name, "unknown", reason, now)
    if not facts.daemon_alive and not facts.daemon_seen:
        # Демона нет вовсе (dev, сервис не развёрнут) — предупреждение, а не авария.
        reason = "Резервное копирование не запущено на этом сервере"
        return Component("backup", name, "warn", reason, now)
    if not facts.daemon_alive:
        reason = "Сервис резервного копирования не отвечает — обратитесь к администратору сервера"
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


def secrets(missing: Sequence[str], now: datetime, *, secrets_key: bool = True) -> Component:
    title = "Секреты сервера"
    if missing:
        names = ", ".join(missing)
        reason = f"Не заданы на сервере: {names} — обратитесь к администратору сервера"
        return Component("secrets", title, "fail", reason, now)
    if not secrets_key:
        reason = "Не задан ключ шифрования (SECRETS_KEY) — токен бота нельзя сменить из интерфейса"
        return Component("secrets", title, "warn", reason, now)
    return Component("secrets", title, "ok", "все обязательные заданы", now)

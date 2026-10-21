"""Правила статусов внешних сервисов (M3-CRM-12, ADR-0024): факты проверки → статус и подсказка.

Чистые функции. Каждый не-`ok` итог несёт: что случилось словами (`summary`), техническую деталь
(`error`, без секретов) и что сделать (`hint`). Вендоры моделей — `domain/external_vendor.py`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal
from urllib.parse import urlsplit

from app.domain.external_registry import ERP_REPORTED_REASON, Status
from app.domain.system_status import BackupFacts, Component, backup_hint

Metric = float | int | str | None
ProbeError = Literal["unauthorized", "timeout", "unavailable", "bad_response"]

TELEGRAM_PENDING_WARN: Final = 100
WEBHOOK_ERROR_FRESH: Final = timedelta(minutes=15)
TLS_FAIL_DAYS: Final = 7
TLS_WARN_DAYS: Final = 21
MAIL_STUCK_AFTER: Final = timedelta(minutes=10)
SERVER_HINT: Final = "Обратитесь к администратору сервера: сервис запускается вместе с ансамблем"


@dataclass(frozen=True, slots=True)
class CheckResult:
    key: str
    status: Status
    summary: str
    error: str | None = None
    hint: str | None = None
    latency_ms: int | None = None
    metrics: Mapping[str, Metric] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HttpFacts:
    """Итог простого health-запроса: ответ получен (`error` None) или класс ошибки."""

    error: ProbeError | None
    detail: str | None = None
    latency_ms: int | None = None


@dataclass(frozen=True, slots=True)
class TelegramFacts:
    configured: bool
    mode: str
    error: ProbeError | None = None
    detail: str | None = None
    username: str | None = None
    pending_updates: int | None = None
    webhook_url: str | None = None
    last_error_message: str | None = None
    last_error_at: datetime | None = None
    latency_ms: int | None = None


def telegram(f: TelegramFacts, now: datetime) -> CheckResult:
    key = "telegram"
    if f.mode == "disabled":
        return CheckResult(key, "off", "Бот выключен настройкой сервера (TELEGRAM_MODE=disabled)")
    if not f.configured:
        return CheckResult(
            key,
            "fail",
            "Токен бота не задан — бот не отвечает клиентам",
            hint="Введите токен в «Подключениях» → «Telegram-бот»",
        )
    if f.error is not None:
        return _telegram_error(f)
    metrics: dict[str, Metric] = {"pending_updates": f.pending_updates, "bot": f.username}
    problem = _webhook_problem(f, now)
    if problem is not None:
        status, summary, hint = problem
        return CheckResult(key, status, summary, f.last_error_message, hint, f.latency_ms, metrics)
    summary = f"Бот @{f.username} отвечает" if f.username else "Бот отвечает"
    return CheckResult(key, "ok", summary, latency_ms=f.latency_ms, metrics=metrics)


def _telegram_error(f: TelegramFacts) -> CheckResult:
    if f.error == "unauthorized":
        return CheckResult(
            "telegram",
            "fail",
            "Telegram не принимает токен бота — бот не работает",
            error=f.detail,
            hint="Выпустите новый токен у @BotFather и введите в «Подключениях» → «Telegram-бот»",
            latency_ms=f.latency_ms,
        )
    return CheckResult(
        "telegram",
        "fail",
        "Нет связи с Telegram — сообщения клиентов не доходят",
        error=f.detail or f.error,
        hint="Проверьте интернет и DNS на сервере; бот переподключится сам",
        latency_ms=f.latency_ms,
    )


def _webhook_problem(f: TelegramFacts, now: datetime) -> tuple[Status, str, str] | None:
    """Бот не получает сообщения (`fail`) или получает с задержкой/ошибками (`warn`)."""
    if f.mode == "webhook" and not f.webhook_url:
        return (
            "fail",
            "Вебхук бота не установлен — Telegram не присылает сообщения",
            "Перезапустите бота: «Подключения» → «Telegram-бот» → сохраните токен ещё раз",
        )
    if f.mode == "polling" and f.webhook_url:
        return (
            "fail",
            "У бота установлен вебхук другого сервера — этот сервер сообщений не получает",
            "Остановите второй стенд с этим токеном или смените токен в «Подключениях»",
        )
    fresh = f.last_error_at is not None and now - f.last_error_at <= WEBHOOK_ERROR_FRESH
    if f.mode == "webhook" and fresh:
        return (
            "warn",
            "Telegram не может доставить сообщения на сервер",
            "Проверьте, что адрес вебхука открывается из интернета и сертификат действителен",
        )
    if (f.pending_updates or 0) > TELEGRAM_PENDING_WARN:
        return (
            "warn",
            f"{f.pending_updates} сообщений ждут обработки — бот не успевает или остановлен",
            "Откройте «Состояние системы»: если бот остановлен — перезапустите сервер CRM",
        )
    return None


@dataclass(frozen=True, slots=True)
class GatewayFacts:
    live: HttpFacts
    ready_db: str | None = None


def litellm(f: GatewayFacts) -> CheckResult:
    key = "litellm"
    if f.live.error is not None:
        return CheckResult(
            key,
            "fail",
            "Шлюз моделей недоступен — бот не отвечает клиентам, ERP без ИИ",
            error=f.live.detail or f.live.error,
            hint=SERVER_HINT,
            latency_ms=f.live.latency_ms,
        )
    if f.ready_db not in (None, "connected"):
        return CheckResult(
            key,
            "warn",
            "Шлюз работает без своей базы — смена моделей и журнал расходов недоступны",
            error=f"db: {f.ready_db}",
            hint=SERVER_HINT,
            latency_ms=f.live.latency_ms,
        )
    return CheckResult(key, "ok", "Шлюз отвечает", latency_ms=f.live.latency_ms)


@dataclass(frozen=True, slots=True)
class LangfuseFacts:
    configured: bool
    health: HttpFacts | None = None
    keys_ok: bool | None = None


def langfuse(f: LangfuseFacts) -> CheckResult:
    key = "langfuse"
    if not f.configured:
        return CheckResult(key, "off", "Не подключён — трейсы ИИ не пишутся (ключи на сервере)")
    health = f.health or HttpFacts("unavailable")
    if health.error is not None:
        return CheckResult(
            key,
            "fail",
            "Langfuse недоступен — трейсы ИИ теряются, бот работает",
            error=health.detail or health.error,
            hint=SERVER_HINT,
            latency_ms=health.latency_ms,
        )
    if f.keys_ok is False:
        return CheckResult(
            key,
            "fail",
            "Langfuse не принимает ключи проекта — трейсы не записываются",
            hint="Обновите LANGFUSE_PUBLIC_KEY и LANGFUSE_SECRET_KEY на сервере",
            latency_ms=health.latency_ms,
        )
    return CheckResult(key, "ok", "Трейсы записываются", latency_ms=health.latency_ms)


@dataclass(frozen=True, slots=True)
class MailFacts:
    configured: bool
    sent_24h: int = 0
    failed_24h: int = 0
    queued: int = 0
    oldest_queued_at: datetime | None = None
    last_error: str | None = None
    last_failed_at: datetime | None = None
    last_sent_at: datetime | None = None
    probe_error: str | None = None
    probe_detail: str | None = None
    probe_latency_ms: int | None = None
    paused: bool = False


_SMTP_HINTS: Final = {
    "auth_failed": "Сервер не принял логин или пароль — обновите их в «Подключениях» → «Почта»",
    "tls_failed": "Не удалось установить шифрование — проверьте порт и режим шифрования",
    "invalid_host": "Адрес сервера некорректен — исправьте в «Подключениях» → «Почта»",
    "unavailable": "Сервер почты не отвечает — проверьте адрес, порт и доступ с сервера",
    "rejected": "Сервер отклонил отправителя или получателя — проверьте адрес отправителя",
}


def mail(f: MailFacts, now: datetime) -> CheckResult:
    key = "mail"
    metrics: dict[str, Metric] = {
        "sent_24h": f.sent_24h,
        "failed_24h": f.failed_24h,
        "queued": f.queued,
    }
    if not f.configured:
        return CheckResult(
            key,
            "off",
            "Не подключена — письма сотрудникам не уходят, пароли передаются вручную",
            hint="Подключите почту в «Подключениях» → «Почта»",
            metrics=metrics,
        )
    if f.probe_error is not None:
        return CheckResult(
            key,
            "fail",
            "Почтовый сервер не принимает подключение — письма не уходят",
            error=f"{f.probe_error}: {f.probe_detail}" if f.probe_detail else f.probe_error,
            hint=_SMTP_HINTS.get(f.probe_error, _SMTP_HINTS["unavailable"]),
            latency_ms=f.probe_latency_ms,
            metrics=metrics,
        )
    stuck = f.oldest_queued_at is not None and now - f.oldest_queued_at > MAIL_STUCK_AFTER
    if stuck and not f.paused:
        return CheckResult(
            key,
            "warn",
            f"{f.queued} писем ждут отправки дольше 10 минут",
            hint="Проверьте «Состояние системы» → «Очередь задач»: воркер должен быть запущен",
            metrics=metrics,
        )
    if _last_failed(f):
        return CheckResult(
            key,
            "warn",
            "Последнее письмо не отправлено",
            error=f.last_error,
            hint="Откройте журнал писем в «Подключениях» → «Почта» и нажмите «Проверить связь»",
            latency_ms=f.probe_latency_ms,
            metrics=metrics,
        )
    return CheckResult(key, "ok", "Письма уходят", latency_ms=f.probe_latency_ms, metrics=metrics)


def _last_failed(f: MailFacts) -> bool:
    if f.last_failed_at is None:
        return False
    return f.last_sent_at is None or f.last_sent_at < f.last_failed_at


def s3(health: HttpFacts, usage: Mapping[str, Metric] | None = None) -> CheckResult:
    metrics = dict(usage or {})
    if health.error is not None:
        return CheckResult(
            "s3",
            "fail",
            "Хранилище файлов недоступно — документы и вложения не сохраняются",
            error=health.detail or health.error,
            hint=SERVER_HINT,
            latency_ms=health.latency_ms,
            metrics=metrics,
        )
    return CheckResult(
        "s3", "ok", "Хранилище отвечает", latency_ms=health.latency_ms, metrics=metrics
    )


def docling(health: HttpFacts | None) -> CheckResult:
    """`None` — `DOCLING_URL` пуст: на этом сервере docling не используется (норма, не авария)."""
    if health is None:
        return CheckResult(
            "docling",
            "off",
            "Не используется на этом сервере — база знаний принимает только Markdown, "
            "документы клиентов не распознаются",
        )
    if health.error is not None:
        return CheckResult(
            "docling",
            "fail",
            "Распознавание документов недоступно — новые файлы базы знаний не индексируются",
            error=health.detail or health.error,
            hint=SERVER_HINT,
            latency_ms=health.latency_ms,
        )
    return CheckResult("docling", "ok", "Сервис отвечает", latency_ms=health.latency_ms)


def backup(
    component: Component, last_copy_hours: float | None, facts: BackupFacts | None = None
) -> CheckResult:
    """Правило бэкапа уже есть (`system_status.backup`, ADR-0013) — здесь только перевод в итог.

    `facts` (M5-CRM-01) добавляет в показатели источник статуса (том или бакет RustFS), время
    последней копии и возраст копии по каждой базе; для бакета — подсказку «что сделать».
    """
    metrics: dict[str, Metric] = {}
    if facts is not None:
        metrics["backup_source"] = facts.source
        metrics["last_copy_at"] = facts.last_success.isoformat() if facts.last_success else None
    metrics["last_copy_hours"] = last_copy_hours
    if facts is not None:
        for db, at in facts.databases.items():
            hours = (
                (component.checked_at - at).total_seconds() / 3600
                if at and component.checked_at
                else None
            )
            metrics[f"db.{db}.hours"] = round(hours, 1) if hours is not None else None
    if component.status == "ok":
        return CheckResult("backup", "ok", component.reason, metrics=metrics)
    if facts is not None and facts.source == "rustfs":
        hint = backup_hint(facts)
        return CheckResult(
            "backup", component.status, component.reason, facts.error_detail, hint, metrics=metrics
        )
    hint = "Откройте «Резервные копии»" if "«Резервн" in component.reason else SERVER_HINT
    return CheckResult("backup", component.status, component.reason, hint=hint, metrics=metrics)


@dataclass(frozen=True, slots=True)
class TlsFacts:
    name: str
    host: str | None
    not_applicable: str | None = None
    days_left: int | None = None
    not_after: datetime | None = None
    error: str | None = None
    detail: str | None = None


def tls(f: TlsFacts) -> CheckResult:
    key = f"tls.{f.name}"
    if f.not_applicable is not None:
        return CheckResult(key, "off", f"Не применимо: {f.not_applicable}")
    metrics: dict[str, Metric] = {
        "host": f.host,
        "days_left": f.days_left,
        "not_after": f.not_after.isoformat() if f.not_after else None,
    }
    if f.error is not None:
        invalid = f.error == "invalid"
        return CheckResult(
            key,
            "fail",
            f"Сертификат {f.host} недействителен" if invalid else f"{f.host} не отвечает по HTTPS",
            error=f.detail or f.error,
            hint="Проверьте DNS домена и журнал Caddy на сервере: сертификат выпускается сам",
            metrics=metrics,
        )
    days = f.days_left if f.days_left is not None else 0
    if days <= TLS_WARN_DAYS:
        status: Status = "fail" if days <= TLS_FAIL_DAYS else "warn"
        return CheckResult(
            key,
            status,
            f"Сертификат {f.host} истекает через {days} дн. — автопродление не сработало",
            hint="Проверьте журнал Caddy и что порт 80/443 открыт из интернета",
            metrics=metrics,
        )
    return CheckResult(key, "ok", f"Действует ещё {days} дн.", metrics=metrics)


_LOCAL_HOSTS: Final = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})  # noqa: S104


def tls_target(url: str) -> tuple[str | None, str | None]:
    """(хост для проверки, почему не применимо): http, локальный адрес или адрес не задан."""
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if not host:
        return None, "адрес не задан"
    if host in _LOCAL_HOSTS or host.endswith(".localhost"):
        return None, "локальный адрес без TLS (dev-стенд)"
    if parts.scheme != "https":
        return None, "адрес без https — TLS не используется"
    return host, None


def tls_days_left(not_after: datetime, now: datetime) -> int:
    return int((not_after - now).total_seconds() // 86400)


STALE_CHEAP: Final = timedelta(minutes=5)
STALE_HEAVY: Final = timedelta(minutes=45)


def stale(checked_at: datetime, tiers: tuple[str, ...], now: datetime) -> bool:
    """Последняя проверка слишком старая: фоновые проверки не идут (воркер остановлен)."""
    limit = STALE_CHEAP if "cheap" in tiers else STALE_HEAVY
    return now - checked_at > limit


def stale_summary(checked_at: datetime, now: datetime) -> tuple[str, str]:
    minutes = int((now - checked_at).total_seconds() // 60)
    return (
        f"Последняя проверка {minutes} мин назад — фоновые проверки не идут",
        "Откройте «Состояние системы» → «Очередь задач»: воркер CRM должен быть запущен",
    )


def never_checked(tiers: tuple[str, ...]) -> str:
    period = "раз в минуту" if "cheap" in tiers else "раз в 15 минут"
    return f"Ещё не проверялся — фоновая проверка {period}"


def erp_reported(key: str) -> CheckResult:
    return CheckResult(key, "unknown", ERP_REPORTED_REASON)

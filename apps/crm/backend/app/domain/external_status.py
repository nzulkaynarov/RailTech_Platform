"""Правила статусов внешних сервисов (M3-CRM-12, ADR-0024): факты проверки → статус и подсказка.

Чистые функции. Каждый не-`ok` итог несёт: что случилось словами (`summary`), техническую деталь
(`error`, без секретов) и что сделать (`hint`). Вендоры моделей — `domain/external_vendor.py`.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Final, Literal
from urllib.parse import urlsplit

from app.domain.external_registry import Status
from app.domain.system_status import (
    HOSTING_WHO,
    BackupFacts,
    Component,
    backup_hint,
    hosting_hint,
)
from app.domain.telegram_webhook import PROBLEM_TEXT, webhook_url_problem

Metric = float | int | str | None
ProbeError = Literal["unauthorized", "timeout", "unavailable", "bad_response"]

TELEGRAM_PENDING_WARN: Final = 100
WEBHOOK_ERROR_FRESH: Final = timedelta(minutes=15)
TLS_FAIL_DAYS: Final = 7
TLS_WARN_DAYS: Final = 21
MAIL_STUCK_AFTER: Final = timedelta(minutes=10)
# Код причины хранится в метриках проверки (служебный ключ с «_» наружу не отдаётся).
CAUSE_METRIC: Final = "_cause"


@dataclass(frozen=True, slots=True)
class CheckResult:
    key: str
    status: Status
    summary: str
    error: str | None = None
    hint: str | None = None
    latency_ms: int | None = None
    metrics: Mapping[str, Metric] = field(default_factory=dict)
    # Машинный код причины (W15-H3): по нему `external_cause` решает, кто исправляет и что делать.
    cause: str | None = None


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
    # Адрес вебхука из настроек CRM (`TELEGRAM_WEBHOOK_URL`) — то, что бот поставил бы сам (FIX-66).
    config_url: str = ""
    # getWebhookInfo не удался: фактический адрес неизвестен.
    webhook_error: str | None = None


def telegram(f: TelegramFacts, now: datetime) -> CheckResult:
    key = "telegram"
    if f.mode == "disabled":
        return CheckResult(
            key,
            "off",
            "Бот выключен настройкой сервера (TELEGRAM_MODE=disabled)",
            cause="intentional",
        )
    if not f.configured:
        return CheckResult(
            key,
            "fail",
            "Токен бота не задан — бот не отвечает клиентам",
            hint="Введите токен в «Подключениях» → «Telegram-бот»",
            cause="no_token",
        )
    metrics: dict[str, Metric] = {
        "pending_updates": f.pending_updates,
        "bot": f.username,
        "webhook_url": f.webhook_url,
        "webhook_error": f.last_error_message,
        "webhook_error_at": f.last_error_at.isoformat() if f.last_error_at else None,
    }
    config = _webhook_config_problem(f)
    if config is not None:
        # `_no_fix`: адрес вебхука не правится в «Подключениях» — кнопка «Исправить» не нужна.
        metrics["_no_fix"] = 1
        return CheckResult(
            key, "fail", *config, latency_ms=f.latency_ms, metrics=metrics, cause="webhook_config"
        )
    if f.error is not None:
        return _telegram_error(f)
    problem = _webhook_problem(f, now)
    if problem is not None:
        status, summary, hint, cause = problem
        return CheckResult(
            key,
            status,
            summary,
            f.last_error_message,
            hint,
            f.latency_ms,
            metrics,
            cause=cause,
        )
    summary = f"Бот @{f.username} отвечает" if f.username else "Бот отвечает"
    return CheckResult(key, "ok", summary, latency_ms=f.latency_ms, metrics=metrics)


def _webhook_config_problem(f: TelegramFacts) -> tuple[str, str, str] | None:
    """(summary, error, hint): режим webhook без годного https-адреса — бот не запущен (FIX-66)."""
    if f.mode != "webhook":
        return None
    problem = webhook_url_problem(f.config_url)
    if problem is None:
        return None
    return (
        "Вебхук Telegram не настроен — бот не запущен и не получает сообщения",
        PROBLEM_TEXT[problem],
        hosting_hint(
            "Публичный адрес CRM для бота на сервере не задан",
            "Задать CRM_DOMAIN в .env сервера (адрес вебхука берётся из него: "
            "https://<CRM_DOMAIN>/telegram/webhook) или TELEGRAM_WEBHOOK_URL с https-адресом "
            "и перезапустить CRM",
        ),
    )


def _telegram_error(f: TelegramFacts) -> CheckResult:
    if f.error == "unauthorized":
        return CheckResult(
            "telegram",
            "fail",
            "Telegram не принимает токен бота — бот не работает",
            error=f.detail,
            hint="Выпустите новый токен у @BotFather и введите в «Подключениях» → «Telegram-бот»",
            latency_ms=f.latency_ms,
            cause="token_rejected",
        )
    return CheckResult(
        "telegram",
        "fail",
        "Нет связи с Telegram — сообщения клиентов не доходят",
        error=f.detail or f.error,
        hint=hosting_hint(
            "Сервер не достаёт до Telegram; бот переподключится сам, когда связь появится",
            "Проверить выход сервера в интернет и DNS (api.telegram.org)",
        ),
        latency_ms=f.latency_ms,
        cause="network",
    )


def _webhook_problem(f: TelegramFacts, now: datetime) -> tuple[Status, str, str, str] | None:
    """Бот не получает сообщения (`fail`) или получает с задержкой/ошибками (`warn`)."""
    if f.mode == "webhook" and f.webhook_error:
        return (
            "warn",
            "Не удалось узнать состояние вебхука — Telegram не отдал getWebhookInfo",
            "Проверка повторится сама; если не проходит — откройте «Состояние системы» и "
            "проверьте связь сервера с api.telegram.org",
            "webhook_info",
        )
    if f.mode == "webhook" and not f.webhook_url:
        return (
            "fail",
            "Вебхук бота не установлен — Telegram не присылает сообщения",
            "Перезапустите бота: «Подключения» → «Telegram-бот» → сохраните токен ещё раз",
            "webhook_state",
        )
    if f.mode == "polling" and f.webhook_url:
        return (
            "fail",
            "У бота установлен вебхук другого сервера — этот сервер сообщений не получает",
            "Остановите второй стенд с этим токеном или смените токен в «Подключениях»",
            "webhook_state",
        )
    fresh = f.last_error_at is not None and now - f.last_error_at <= WEBHOOK_ERROR_FRESH
    if f.mode == "webhook" and fresh:
        return (
            "warn",
            "Telegram не может доставить сообщения на сервер",
            hosting_hint(
                "Telegram не достаёт до сервера по адресу вебхука",
                "Открыть адрес вебхука бота из интернета и проверить, что сертификат действителен",
            ),
            "webhook_delivery",
        )
    if (f.pending_updates or 0) > TELEGRAM_PENDING_WARN:
        return (
            "warn",
            f"{f.pending_updates} сообщений ждут обработки — бот не успевает или остановлен",
            "Откройте «Состояние системы»: если бот остановлен — перезапустите сервер CRM",
            "backlog",
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
            hint=hosting_hint(
                "Шлюз моделей не запущен на сервере",
                "Запустить шлюз моделей (litellm) вместе с ансамблем",
            ),
            latency_ms=f.live.latency_ms,
            cause="server_down",
        )
    if f.ready_db not in (None, "connected"):
        return CheckResult(
            key,
            "warn",
            "Шлюз работает без своей базы — смена моделей и журнал расходов недоступны",
            error=f"db: {f.ready_db}",
            hint=hosting_hint(
                "Шлюз моделей не видит свою базу данных",
                "Проверить базу шлюза моделей (litellm) и её подключение",
            ),
            latency_ms=f.live.latency_ms,
            cause="gateway_db",
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
        return CheckResult(
            key,
            "off",
            "Не подключён — трейсы ИИ не пишутся (ключи на сервере)",
            cause="intentional",  # необязательный сервис: не «Требует внимания»
        )
    health = f.health or HttpFacts("unavailable")
    if health.error is not None:
        return CheckResult(
            key,
            "fail",
            "Langfuse недоступен — трейсы ИИ теряются, бот работает",
            error=health.detail or health.error,
            hint=hosting_hint(
                "Сервис журнала работы ИИ (Langfuse) не запущен или не отвечает",
                "Запустить langfuse вместе с ансамблем",
            ),
            latency_ms=health.latency_ms,
            cause="server_down",
        )
    if f.keys_ok is False:
        return CheckResult(
            key,
            "fail",
            "Langfuse не принимает ключи проекта — трейсы не записываются",
            hint=hosting_hint(
                "Ключи проекта Langfuse на сервере устарели",
                "Обновить LANGFUSE_PUBLIC_KEY и LANGFUSE_SECRET_KEY в .env сервера",
            ),
            latency_ms=health.latency_ms,
            cause="langfuse_keys",
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
            cause="not_configured",
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
            cause=f"smtp_{f.probe_error}" if f.probe_error in _SMTP_HINTS else "smtp_unavailable",
        )
    stuck = f.oldest_queued_at is not None and now - f.oldest_queued_at > MAIL_STUCK_AFTER
    if stuck and not f.paused:
        return CheckResult(
            key,
            "warn",
            f"{f.queued} писем ждут отправки дольше 10 минут",
            hint=hosting_hint(
                "Письма стоят в очереди: фоновый обработчик (воркер CRM) не запущен",
                "Запустить crm-worker вместе с ансамблем",
            ),
            metrics=metrics,
            cause="queue_stuck",
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
            cause="last_failed",
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
            hint=hosting_hint(
                "Хранилище файлов не запущено или не отвечает на сервере",
                "Запустить хранилище файлов (rustfs) вместе с ансамблем и проверить доступы",
            ),
            latency_ms=health.latency_ms,
            metrics=metrics,
            cause="server_down",
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
            cause="intentional",
        )
    if health.error is not None:
        return CheckResult(
            "docling",
            "fail",
            "Распознавание документов недоступно — новые файлы базы знаний не индексируются",
            error=health.detail or health.error,
            hint=hosting_hint(
                "Сервис распознавания документов не запущен на сервере",
                "Запустить docling вместе с ансамблем",
            ),
            latency_ms=health.latency_ms,
            cause="server_down",
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
            "backup",
            component.status,
            component.reason,
            facts.error_detail,
            hint,
            metrics=metrics,
            cause="backup_admin",
        )
    if "«Резервн" in component.reason:
        return CheckResult(
            "backup",
            component.status,
            component.reason,
            hint="Откройте «Резервные копии»",
            metrics=metrics,
            cause="backup_admin",
        )
    hint = None
    if HOSTING_WHO not in component.reason:
        hint = hosting_hint(
            "Резервное копирование на сервере не работает",
            "Запустить сервис резервных копий (backup) и проверить, что копии пишутся",
        )
    return CheckResult(
        "backup",
        component.status,
        component.reason,
        hint=hint,
        metrics=metrics,
        cause="server_down",
    )


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
        return CheckResult(key, "off", f"Не применимо: {f.not_applicable}", cause="intentional")
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
            hint=hosting_hint(
                f"Сертификат {f.host} не выпускается или не отвечает",
                f"Проверить DNS домена {f.host} и журнал Caddy на сервере",
            ),
            metrics=metrics,
            cause="cert",
        )
    days = f.days_left if f.days_left is not None else 0
    if days <= TLS_WARN_DAYS:
        status: Status = "fail" if days <= TLS_FAIL_DAYS else "warn"
        return CheckResult(
            key,
            status,
            f"Сертификат {f.host} истекает через {days} дн. — автопродление не сработало",
            hint=hosting_hint(
                f"Сертификат {f.host} скоро истечёт: автопродление не сработало",
                "Проверить журнал Caddy и что порты 80 и 443 открыты из интернета",
            ),
            metrics=metrics,
            cause="cert_expiring",
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


# Сломанное перепроверяется с затуханием (до раза в 15 мин) — пауза между проверками не «устарело».
STALE_BACKING_OFF: Final = timedelta(minutes=20)


def stale(
    checked_at: datetime, tiers: tuple[str, ...], now: datetime, *, backing_off: bool = False
) -> bool:
    """Последняя проверка слишком старая: фоновые проверки не идут (воркер остановлен)."""
    limit = STALE_CHEAP if "cheap" in tiers else STALE_HEAVY
    if backing_off:
        limit = max(limit, STALE_BACKING_OFF)
    return now - checked_at > limit


def stale_summary(checked_at: datetime, now: datetime) -> tuple[str, str]:
    minutes = int((now - checked_at).total_seconds() // 60)
    return (
        f"Последняя проверка {minutes} мин назад — фоновые проверки не идут",
        hosting_hint(
            "Фоновые проверки остановились: воркер CRM не запущен "
            "или не выполняет периодические задачи",
            "Запустить crm-worker вместе с ансамблем; если он работает — посмотреть его журнал",
        ),
    )


def never_checked(tiers: tuple[str, ...]) -> str:
    period = "раз в минуту" if "cheap" in tiers else "раз в 15 минут"
    return f"Не проверено — нажмите «Проверить» (фоновая проверка {period})"

"""Инфраструктура ансамбля в центре внешних сервисов (W15-H8b, B-004/B-005): архив WAL, Redis, шина,
публикация прав EDS.

Чистые функции: факты проверки → `CheckResult` с причиной, «кто исправляет» и подсказкой хостингу.
Ни архив журнала БД, ни Redis CRM сама не использует, поэтому о падении было бы известно только по
последствиям (ERP без очередей, Платформа без сессий, архив без новых сегментов). Строки идут тем
же путём, что остальные: затухание перепроверок, одно «Сломано» и одно «Восстановлено» на причину.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from app.domain.external_status import CheckResult, Metric
from app.domain.system_status import hosting_hint

# --- архив WAL ---------------------------------------------------------------------------------

#: Сегмент журнала в каталоге `wal_005/`: имя из 24 шестнадцатеричных цифр (время, журнал, сегмент).
_SEGMENT: Final = re.compile(r"(?:^|/)[0-9A-F]{24}(?:\.|$)")
SENTINEL_SUFFIX: Final = "_backup_stop_sentinel.json"
#: `archive_timeout = 60 с`: сегмент уходит раз в минуту, пока в базе есть запись (CRM пишет всегда:
#: пульс бота, очередь). Больше 10 минут без нового сегмента — архив отстаёт, больше 30 — стоит.
SEGMENT_WARN: Final = timedelta(minutes=10)
SEGMENT_FAIL: Final = timedelta(minutes=30)
#: Базовая копия — раз в сутки (21:00 UTC); 26 часов — healthcheck `walg`, двое суток — копии нет.
BASEBACKUP_WARN: Final = timedelta(hours=26)
BASEBACKUP_FAIL: Final = timedelta(hours=50)
WAL_CHECK_NOTE: Final = (
    "Аварийный выключатель архива (файл rt-archive-off на сервере базы) CRM не видит: о нём "
    "говорит остановка новых сегментов; сам файл и красный walg — docker ps на сервере базы"
)


def is_segment(key: str) -> bool:
    return bool(_SEGMENT.search(key))


def is_sentinel(key: str) -> bool:
    return key.endswith(SENTINEL_SUFFIX)


@dataclass(frozen=True, slots=True)
class WalFacts:
    """Что CRM увидела в каталоге архива; `error` — каталог прочитать не удалось."""

    error: str | None = None
    last_segment_at: datetime | None = None
    last_basebackup_at: datetime | None = None


def _minutes(delta: timedelta) -> int:
    return int(delta.total_seconds() // 60)


def _wal_hint(what: str, ask: str) -> str:
    return hosting_hint(what, ask) + ". " + WAL_CHECK_NOTE


def wal_archive(f: WalFacts, now: datetime) -> CheckResult:
    key = "wal_archive"
    if f.error is not None:
        return CheckResult(
            key,
            "unknown",
            "Архив WAL не проверен: CRM не смогла прочитать каталог архива в хранилище",
            error=f.error,
            hint=hosting_hint(
                "CRM не читает бакет архива WAL (wal): состояние видно только на сервере базы",
                "Выдать сервису CRM чтение бакета wal (s3-init) и проверить WAL_S3_PREFIX; "
                "до этого состояние архива: docker exec -u postgres rt-db-walg-1 rt-pitr status",
            ),
            cause="server_down",
        )
    metrics: dict[str, Metric] = {
        "last_segment_at": f.last_segment_at.isoformat() if f.last_segment_at else None,
        "last_segment_min": _minutes(now - f.last_segment_at) if f.last_segment_at else None,
        "last_basebackup_at": f.last_basebackup_at.isoformat() if f.last_basebackup_at else None,
        "last_basebackup_hours": (
            round((now - f.last_basebackup_at).total_seconds() / 3600, 1)
            if f.last_basebackup_at
            else None
        ),
    }
    if f.last_segment_at is None:
        return CheckResult(
            key,
            "fail",
            "Архива WAL нет: в хранилище нет ни одного сегмента журнала базы",
            hint=_wal_hint(
                "Непрерывный архив базы не пишется: восстановление на момент времени невозможно",
                "Запустить сервис walg и проверить archive_command PostgreSQL на сервере базы",
            ),
            metrics=metrics,
            cause="server_down",
        )
    age = now - f.last_segment_at
    if age > SEGMENT_FAIL:
        return CheckResult(
            key,
            "fail",
            f"Архив WAL остановился: последний сегмент {_minutes(age)} мин назад",
            hint=_wal_hint(
                "Архив журнала базы не получает новые сегменты: WAL копится на диске сервера базы",
                "Проверить сервис walg и archive_command PostgreSQL (docker ps, rt-pitr status); "
                "возможно, включён аварийный выключатель архива",
            ),
            metrics=metrics,
            cause="server_down",
        )
    problems: list[tuple[Literal["warn", "fail"], str]] = []
    if age > SEGMENT_WARN:
        problems.append(("warn", f"архив отстаёт: последний сегмент {_minutes(age)} мин назад"))
    if f.last_basebackup_at is None:
        problems.append(("fail", "базовых копий архива нет"))
    else:
        base_age = now - f.last_basebackup_at
        hours = int(base_age.total_seconds() // 3600)
        if base_age > BASEBACKUP_FAIL:
            problems.append(("fail", f"базовая копия архива {hours} ч назад"))
        elif base_age > BASEBACKUP_WARN:
            problems.append(
                ("warn", f"базовая копия архива {hours} ч назад (должна быть раз в сутки)")
            )
    if problems:
        status: Literal["warn", "fail"] = (
            "fail" if any(s == "fail" for s, _ in problems) else "warn"
        )
        text = "; ".join(t for _, t in problems)
        return CheckResult(
            key,
            status,
            "Архив WAL: " + text,
            hint=_wal_hint(
                "Архив журнала базы работает с перебоями",
                "Проверить сервис walg: docker logs rt-db-walg-1, rt-pitr status "
                "(базовая копия — walg-daemon --backup-now)",
            ),
            metrics=metrics,
            cause="server_down",
        )
    base_hours = metrics["last_basebackup_hours"]
    return CheckResult(
        key,
        "ok",
        f"Архив пишется: последний сегмент {_minutes(age)} мин назад, "
        f"базовая копия {base_hours} ч назад",
        metrics=metrics,
    )


# --- Redis -------------------------------------------------------------------------------------

REDIS_BROKER: Final = "redis_broker"
REDIS_CACHE: Final = "redis_cache"
#: Брокер не вытесняет данные (`noeviction`): у потолка памяти запись падает и очереди встают.
MEMORY_WARN: Final = 0.80
MEMORY_FAIL: Final = 0.95
#: Кэш вытесняет сам, поэтому память — только предупреждение; снимок RDB — раз в 5 минут.
RDB_STALE_S: Final = 3600
_ROLE_TEXT: Final = {
    REDIS_BROKER: (
        "Брокер Redis",
        "ERP не обрабатывает фоновые задачи (Celery, Channels), Langfuse не пишет трейсы",
    ),
    REDIS_CACHE: (
        "Кэш Redis",
        "сессии Платформы, кэш и троттлинг ERP — сотрудников выбросит из Платформы",
    ),
}


def parse_info(text: str) -> dict[str, str]:
    """Ответ `INFO`: строки `ключ:значение`, секции и пустые строки пропускаются."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and ":" in line:
            name, _, value = line.partition(":")
            out[name.strip()] = value.strip()
    return out


@dataclass(frozen=True, slots=True)
class RedisFacts:
    key: str
    configured: bool = True
    error: str | None = None
    latency_ms: int | None = None
    info: Mapping[str, str] | None = None


def _int(info: Mapping[str, str], name: str) -> int | None:
    try:
        return int(info[name])
    except (KeyError, ValueError):
        return None


def redis(f: RedisFacts, now: datetime) -> CheckResult:
    title, impact = _ROLE_TEXT[f.key]
    if not f.configured:
        return CheckResult(
            f.key,
            "unknown",
            f"{title} не проверен: адрес не задан в окружении CRM",
            hint=hosting_hint(
                f"CRM не знает адрес {title.lower()} и не может проверить его",
                "Выложить текущий релиз: деплой сам создаёт REDIS_PROBE_PASSWORD "
                "(пользователь пробы crm-probe) и адреса REDIS_BROKER_URL, REDIS_CACHE_URL",
            ),
            cause="server_down",
        )
    if f.error is not None or f.info is None:
        return CheckResult(
            f.key,
            "fail",
            f"{title} не отвечает — {impact}",
            error=f.error,
            latency_ms=f.latency_ms,
            hint=hosting_hint(
                f"{title} не запущен или не принимает подключения",
                f"Запустить {f.key.replace('_', '-')} и проверить пароль и память "
                "(docker ps, docker logs)",
            ),
            cause="server_down",
        )
    info = f.info
    used, limit = _int(info, "used_memory"), _int(info, "maxmemory")
    ratio = used / limit if used is not None and limit else None
    saved = _int(info, "rdb_last_save_time")
    save_age = int(now.timestamp()) - saved if saved else None
    metrics: dict[str, Metric] = {
        "used_memory_mb": round(used / 1048576, 1) if used is not None else None,
        "maxmemory_mb": round(limit / 1048576) if limit else None,
        "memory_pct": round(ratio * 100) if ratio is not None else None,
        "rdb_last_save_age_s": save_age,
        "latency_ms": f.latency_ms,
    }
    problems: list[tuple[Literal["warn", "fail"], str]] = []
    if info.get("aof_last_write_status") == "err":
        problems.append(("fail", "журнал AOF не пишется на диск — очередь не переживёт рестарт"))
    if ratio is not None and ratio >= MEMORY_FAIL and f.key == REDIS_BROKER:
        problems.append(("fail", f"память {round(ratio * 100)} % от лимита: запись скоро встанет"))
    elif ratio is not None and ratio >= MEMORY_WARN:
        problems.append(("warn", f"память {round(ratio * 100)} % от лимита"))
    if info.get("rdb_last_bgsave_status") == "err":
        problems.append(("warn", "снимок RDB не сохраняется"))
    elif f.key == REDIS_CACHE and save_age is not None and save_age > RDB_STALE_S:
        problems.append(("warn", f"снимок RDB не обновлялся {save_age // 60} мин"))
    if problems:
        status: Literal["warn", "fail"] = (
            "fail" if any(s == "fail" for s, _ in problems) else "warn"
        )
        return CheckResult(
            f.key,
            status,
            f"{title}: " + "; ".join(t for _, t in problems),
            latency_ms=f.latency_ms,
            hint=hosting_hint(
                f"{title} работает с проблемами",
                f"Проверить память, диск и журнал {f.key.replace('_', '-')} "
                "(docker logs, INFO memory)",
            ),
            metrics=metrics,
            cause="server_down",
        )
    memory = f", память {metrics['memory_pct']} %" if ratio is not None else ""
    return CheckResult(
        f.key, "ok", f"{title} отвечает{memory}", latency_ms=f.latency_ms, metrics=metrics
    )


# --- шина: недоставленное ----------------------------------------------------------------------

BUS_DLQ: Final = "bus_dlq"


@dataclass(frozen=True, slots=True)
class BusDlqFacts:
    """DLQ шины CRM без ERP (его недоставленное — строка «События из ERP»): доставки подписчикам
    в статусе `dead` и принятые события, которые обработчик не смог разобрать (`failed`)."""

    dead: int
    failed: int
    last_error: str | None = None


def bus_dlq(f: BusDlqFacts) -> CheckResult:
    metrics: dict[str, Metric] = {"dead": f.dead, "failed": f.failed}
    if not (f.dead or f.failed):
        return CheckResult(BUS_DLQ, "ok", "Шина: недоставленных событий нет", metrics=metrics)
    parts = []
    if f.dead:
        parts.append(f"не доставлено: {f.dead}")
    if f.failed:
        parts.append(f"не обработано: {f.failed}")
    return CheckResult(
        BUS_DLQ,
        "fail",
        "Шина: " + ", ".join(parts),
        error=f.last_error,
        hint=(
            "Откройте журнал обмена (Настройки · Журнал интеграций): там видно, какому "
            "подписчику и почему событие не дошло, и можно повторить доставку"
        ),
        metrics=metrics,
        cause=BUS_DLQ,
    )


# --- права EDS сотрудников (B-005) -------------------------------------------------------------

EDS_RIGHTS: Final = "eds_rights"


@dataclass(frozen=True, slots=True)
class EdsRightsFacts:
    """Опубликованы ли права EDS по действующему каталогу.

    `stored` — отпечаток, под которым CRM последний раз переопубликовала снимки сотрудников (нет
    записи — публикации ещё не было); `current` — отпечаток действующего каталога. Различаются —
    сотрудники не получили новые права EDS и молча видят «нет доступа». `republished` — проверка
    сама повторила публикацию и она удалась; `error` — повтор не удался (или ещё не пробовался)."""

    stored: str | None
    current: str
    users: int = 0
    republished: bool = False
    error: str | None = None


def eds_rights(f: EdsRightsFacts) -> CheckResult:
    metrics: dict[str, Metric] = {"published_users": f.users}
    if f.republished or f.stored == f.current:
        done = f" (переопубликовано сотрудников: {f.users})" if f.republished else ""
        return CheckResult(EDS_RIGHTS, "ok", f"Права EDS опубликованы{done}", metrics=metrics)
    return CheckResult(
        EDS_RIGHTS,
        "fail",
        "Права EDS не опубликованы: сотрудники не получили новые права",
        error=f.error,
        hint=hosting_hint(
            "После смены каталога ролей права EDS сотрудников не ушли на шину, и они получают "
            "«нет доступа» в EDS. Проверка повторяет публикацию сама; пока не удалось — шина или "
            "база недоступны",
            "выполнить на сервере CRM команду python -m app republish-identity и проверить шину "
            "и доступность EDS",
        ),
        metrics=metrics,
        cause=EDS_RIGHTS,
    )

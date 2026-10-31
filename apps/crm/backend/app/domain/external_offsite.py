"""Внешняя копия бэкапов (Яндекс Диск или Google Drive) в центре внешних сервисов (OPS-GDRIVE,
OPS-YADISK).

Чистые функции: отметка сервиса `offsite-backup` (`status.json` в бакете `offsite`, пишет
`infra/offsite/offsite-sync.sh`) → `CheckResult` с провайдером, причиной и «кто исправляет». CRM не
ходит ни на Диск, ни в архив WAL: задача копирования записывает итог каждой попытки, CRM читает файл
ключом
«только чтение» — тот же принцип наименьших прав, что у пробы Redis `crm-probe`. Возраст последнего
успеха считает сама CRM: остановленная задача (контейнер упал, отметка старая) — тоже «сбой», а не
вечный «ok». Строка идёт по общей политике H3: непрерывный сбой 15 минут — «Сломано».
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from app.domain.external_status import CheckResult, Metric
from app.domain.system_status import hosting_hint

KEY: Final = "offsite_backup"
STATUS_KEY: Final = "status.json"
#: Копия — раз в сутки (23:00 UTC); 26 часов — как у базовой копии WAL-G: сутки и запас на копию.
STALE_AFTER: Final = timedelta(hours=26)
#: Доля предела OFFSITE_MAX_GB, с которой — предупреждение (больше предела копия не выгружается).
QUOTA_WARN: Final = 0.8
RUNBOOK: Final = "docs/runbooks/offsite-gdrive.md"
OWNER_WHO: Final = "Кто исправляет: владелец"
#: Куда идёт копия: `provider` из status.json; старые отметки (до OPS-YADISK) — Google Drive.
PROVIDERS: Final = ("yandex", "gdrive")
_TO: Final = {"yandex": "на Яндекс Диск", "gdrive": "на Google Drive"}
_AT: Final = {"yandex": "на Яндекс Диске", "gdrive": "на Google Drive"}
_SCREEN: Final = "«Внешней копии бэкапов» (Admin → Подключения → «Хранилище»)"
#: Причины, которые исправляет владелец (доступ, папка, место на Диске).
CAUSE_NOT_CONFIGURED: Final = "offsite_not_configured"
CAUSE_ACCESS: Final = "offsite_access"
CAUSE_QUOTA: Final = "offsite_quota"
SETUP_STEPS: Final = (
    "в Яндекс ID аккаунта компании (Яндекс 360) создать пароль приложения типа «Файлы» "
    "(Безопасность → Пароли приложений), затем в Платформе: Admin → Подключения → «Хранилище» → "
    "«Внешняя копия бэкапов» — выбрать «Яндекс Диск», ввести адрес почты и пароль приложения и "
    "нажать «Сохранить и проверить»; Google Drive подходит только с общим диском Google Workspace; "
    f"на сервер заходить не нужно (по шагам — {RUNBOOK})"
)
_YANDEX_TODO: Final = {
    "access": (
        f"проверить в {_SCREEN} логин — адрес почты Яндекс 360 — и пароль приложения типа «Файлы» "
        "(Яндекс ID → Безопасность → Пароли приложений; удалённый пароль — создать заново), а в "
        "админке Яндекс 360 — что доступ к Диску по WebDAV не закрыт; там же — «Проверить»"
    ),
    "quota": (
        "освободить место на Яндекс Диске компании (и очистить его Корзину) или поднять "
        "OFFSITE_MAX_GB в /opt/rt/.env.prod (затем infra/deploy/offsite-check.sh)"
    ),
}
_OWNER_TODO: Final = {
    "access": (
        "проверить в папке общего диска, что сервисному аккаунту выдана роль «Менеджер контента», "
        "ключ не отозван в Google Cloud, а в «Внешней копии бэкапов» (Admin → Подключения → "
        "«Хранилище») указана эта папка; там же — «Проверить»"
    ),
    "not_shared_drive": (
        "создать папку на общем диске (Shared Drive), а не в «Моём диске», выдать в ней "
        "сервисному аккаунту роль «Менеджер контента» и указать её в «Внешней копии бэкапов»"
    ),
    "quota": (
        "освободить место на общем диске Google или поднять OFFSITE_MAX_GB в /opt/rt/.env.prod "
        "(затем infra/deploy/offsite-check.sh)"
    ),
}
_OWNER_CAUSE: Final = {
    "access": CAUSE_ACCESS,
    "not_shared_drive": CAUSE_ACCESS,
    "quota": CAUSE_QUOTA,
}


@dataclass(frozen=True, slots=True)
class OffsiteFacts:
    """Что CRM прочитала в отметке; `error` — прочитать не удалось, `missing` — отметки ещё нет.
    `speed_bps` — средняя скорость последней выгрузки (Яндекс местами ограничивает WebDAV)."""

    error: str | None = None
    missing: bool = False
    provider: str = ""
    result: str | None = None
    reason: str = ""
    message: str = ""
    detail: str = ""
    attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    size_bytes: int | None = None
    objects: int | None = None
    base_backups: int | None = None
    oldest_base_at: datetime | None = None
    quota_bytes: int | None = None
    keep_days: int | None = None
    speed_bps: int | None = None


def _when(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _int(raw: object) -> int | None:
    return raw if isinstance(raw, int) and not isinstance(raw, bool) else None


def _text(raw: object) -> str:
    return raw if isinstance(raw, str) else ""


def parse(raw: bytes) -> OffsiteFacts:
    """Отметка задачи копирования; битый или чужой файл — «не проверено», а не авария."""
    try:
        data = json.loads(raw)
    except ValueError:
        return OffsiteFacts(error="bad_status_json")
    if not isinstance(data, dict) or data.get("result") not in ("ok", "fail", "not_configured"):
        return OffsiteFacts(error="bad_status_json")
    provider = data.get("provider", "gdrive")  # до OPS-YADISK копия была только на Google Drive
    return OffsiteFacts(
        provider=provider if provider in PROVIDERS else "",
        result=str(data["result"]),
        reason=_text(data.get("reason")),
        message=_text(data.get("message")),
        detail=_text(data.get("detail")),
        attempt_at=_when(data.get("attempt_at")),
        last_success_at=_when(data.get("last_success_at")),
        size_bytes=_int(data.get("bytes")),
        objects=_int(data.get("objects")),
        base_backups=_int(data.get("base_backups")),
        oldest_base_at=_when(data.get("oldest_base_at")),
        quota_bytes=_int(data.get("quota_bytes")),
        keep_days=_int(data.get("keep_days")),
        speed_bps=_int(data.get("speed_bps")),
    )


def size_text(value: int) -> str:
    """«350 МБ», «12,4 ГБ» — объём по-русски, десятичная запятая."""
    mb = value / 1048576
    if mb < 1024:
        return f"{max(round(mb), 0)} МБ"
    return f"{mb / 1024:.1f}".replace(".", ",") + " ГБ"


def _to(f: OffsiteFacts) -> str:
    return _TO.get(f.provider, "во внешнее хранилище")


def _at(f: OffsiteFacts) -> str:
    return _AT.get(f.provider, "во внешнем хранилище")


def _todo(f: OffsiteFacts) -> str:
    if f.provider == "yandex" and f.reason in _YANDEX_TODO:
        return _YANDEX_TODO[f.reason]
    return _OWNER_TODO[f.reason]


def speed_text(bps: int) -> str:
    """«1,8 МБ/с», «640 КБ/с» — средняя скорость выгрузки."""
    if bps >= 1048576:
        return f"{bps / 1048576:.1f}".replace(".", ",") + " МБ/с"
    return f"{max(round(bps / 1024), 0)} КБ/с"


def owner_hint(what: str, todo: str) -> str:
    """«Что случилось. Кто исправляет: владелец. Что сделать: …» — ключ и папка Google — его."""
    return f"{what}. {OWNER_WHO}. Что сделать: {todo}"


def _hours(delta: timedelta) -> int:
    return int(delta.total_seconds() // 3600)


def _metrics(f: OffsiteFacts, now: datetime) -> dict[str, Metric]:
    size, quota = f.size_bytes, f.quota_bytes
    ratio = size / quota if size is not None and quota else None
    return {
        "last_success_at": f.last_success_at.isoformat() if f.last_success_at else None,
        "last_success_hours": (
            round((now - f.last_success_at).total_seconds() / 3600, 1)
            if f.last_success_at
            else None
        ),
        "attempt_at": f.attempt_at.isoformat() if f.attempt_at else None,
        "bytes": f.size_bytes,
        "objects": f.objects,
        "base_backups": f.base_backups,
        "oldest_base_at": f.oldest_base_at.isoformat() if f.oldest_base_at else None,
        "quota_bytes": f.quota_bytes,
        "quota_pct": round(ratio * 100) if ratio is not None else None,
        "keep_days": f.keep_days,
        "speed_bps": f.speed_bps,
        "provider": f.provider or None,
        "reason": f.reason or None,
    }


def _failure(
    f: OffsiteFacts, now: datetime, metrics: Mapping[str, Metric], stale: bool
) -> CheckResult:
    """Сбой: последняя попытка с ошибкой или успешной копии нет дольше 26 часов."""
    age = (
        f" Последняя успешная копия {_hours(now - f.last_success_at)} ч назад."
        if f.last_success_at
        else " Успешной копии ещё не было."
    )
    if f.result == "fail" and f.reason in _OWNER_TODO:
        what = f.message or f"Копирование {_to(f)} отклонено"
        return CheckResult(
            KEY,
            "fail",
            f"Внешняя копия бэкапов не обновляется: {what}",
            error=f.detail or None,
            hint=owner_hint(what + "." + age, _todo(f)),
            metrics=dict(metrics),
            cause=_OWNER_CAUSE[f.reason],
        )
    if f.result == "fail":
        what = f.message or f"Копирование {_to(f)} завершилось ошибкой"
        summary = f"Внешняя копия бэкапов не обновляется: {what}"
        place = "Яндекс Диском (webdav.yandex.ru)" if f.provider == "yandex" else "Google Drive"
        ask = (
            "Проверить сервис offsite-backup на сервере приложений: docker compose logs "
            f"offsite-backup, связь сервера с {place} и бакет wal; повтор — "
            "infra/deploy/offsite-check.sh"
        )
    else:
        hours = _hours(now - f.last_success_at) if f.last_success_at else None
        summary = (
            f"Внешняя копия бэкапов устарела: последняя успешная копия {hours} ч назад"
            if stale and hours is not None
            else "Внешняя копия бэкапов устарела"
        )
        what = f"Сервис копирования {_to(f)} не отмечается: он остановлен или завис"
        ask = (
            "Запустить сервис offsite-backup на сервере приложений (docker compose ps, logs "
            "offsite-backup; выложить текущий релиз)"
        )
    return CheckResult(
        KEY,
        "fail",
        summary,
        error=f.detail or None,
        hint=hosting_hint(what + "." + age, ask),
        metrics=dict(metrics),
        cause="server_down",
    )


def offsite_backup(f: OffsiteFacts, now: datetime) -> CheckResult:
    if f.error is not None:
        return CheckResult(
            KEY,
            "unknown",
            "Внешняя копия не проверена: CRM не смогла прочитать отметку сервиса копирования",
            error=f.error,
            hint=hosting_hint(
                "CRM не читает бакет offsite с отметкой внешней копии (status.json)",
                "Выдать сервису CRM чтение offsite/status.json (s3-init при деплое); до этого "
                "состояние копии: docker compose logs offsite-backup на сервере приложений",
            ),
            cause="server_down",
        )
    if f.missing or f.result == "not_configured":
        what = (
            f.message
            if f.result == "not_configured" and f.message
            else "Сервис копирования ещё не отметился: копия не настроена или сервис не запущен"
        )
        return CheckResult(
            KEY,
            "off",
            f"Внешняя копия бэкапов не настроена: {what}",
            hint=owner_hint(
                "Копии базы вне наших серверов нет: при потере обоих серверов данные не вернуть",
                SETUP_STEPS,
            ),
            metrics={
                "reason": f.reason or ("no_status" if f.missing else None),
                "provider": f.provider or None,
            },
            cause=CAUSE_NOT_CONFIGURED,
        )
    metrics = _metrics(f, now)
    last = f.last_success_at
    stale = last is None or now - last > STALE_AFTER
    if f.result == "fail" or last is None or stale:
        return _failure(f, now, metrics, stale)
    hours = _hours(now - last)
    parts = []
    if f.size_bytes is not None:
        parts.append(size_text(f.size_bytes))
    if f.base_backups is not None:
        since = f" (с {f.oldest_base_at:%d.%m})" if f.oldest_base_at else ""
        parts.append(f"базовых копий {f.base_backups}{since}")
    if f.speed_bps:
        parts.append(f"средняя скорость {speed_text(f.speed_bps)}")
    tail = f": {', '.join(parts)}" if parts else ""
    pct = metrics["quota_pct"]
    if isinstance(pct, int) and pct >= QUOTA_WARN * 100:
        quota = _YANDEX_TODO if f.provider == "yandex" else _OWNER_TODO
        return CheckResult(
            KEY,
            "warn",
            f"Внешняя копия бэкапов: занято {pct} % предела копии {_at(f)}",
            hint=owner_hint(
                f"Копия {_at(f)} близка к пределу OFFSITE_MAX_GB: больше предела "
                "копирование остановится",
                quota["quota"],
            ),
            metrics=metrics,
            cause=CAUSE_QUOTA,
        )
    return CheckResult(
        KEY,
        "ok",
        f"Копия {_at(f)} обновлена {hours} ч назад{tail}",
        metrics=metrics,
    )

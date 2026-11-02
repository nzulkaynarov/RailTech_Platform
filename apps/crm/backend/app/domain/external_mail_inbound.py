"""Приём почты общего ящика в центре внешних сервисов (W18A-P2, B-INB-5): строка здоровья.

Чистая функция: итог последнего опроса IMAP (`inbound_mailbox`: когда опрашивали, когда удачно,
причина сбоя словом-кодом) → `CheckResult`. CRM не ходит в ящик ради проверки: опрос раз в 2 минуты
и так входит в ящик, проверка читает его итог. Опрос не идёт дольше 10 минут — воркер не работает.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from app.domain.external_status import CheckResult, Metric
from app.domain.system_status import hosting_hint

KEY: Final = "mail_inbound"
STALE_AFTER: Final = timedelta(minutes=10)
_HINTS: Final = {
    "auth_failed": "Почтовый сервер не принял логин или пароль приложения — введите их заново в "
    "«Подключениях» → «Почта» → «Приём»",
    "mailbox_missing": "Нет такой папки в ящике — проверьте поле «Папка» (обычно INBOX)",
    "invalid_host": "Проверьте адрес сервера IMAP (например, imap.yandex.ru)",
    "tls_failed": "Не удалось установить защищённое соединение — проверьте порт и способ "
    "шифрования (993 — SSL)",
    "unavailable": "Сервер IMAP не отвечает — проверьте адрес и порт, затем «Проверить приём»",
}


@dataclass(frozen=True, slots=True)
class InboundFacts:
    configured: bool
    last_poll_at: datetime | None = None
    last_ok_at: datetime | None = None
    error_kind: str | None = None
    error: str | None = None
    waiting: int = 0


def mail_inbound(f: InboundFacts, now: datetime) -> CheckResult:
    metrics: dict[str, Metric] = {"waiting": f.waiting}
    if not f.configured:
        return CheckResult(
            KEY,
            "off",
            "Не подключён — письма общего ящика не попадают в очередь «Входящая почта»",
            hint="Подключите приём в «Подключениях» → «Почта» → «Приём»",
            metrics=metrics,
            cause="not_configured",
        )
    if f.error_kind is not None:
        return CheckResult(
            KEY,
            "fail",
            "Ящик не открывается — новые письма не попадают в очередь",
            error=f"{f.error_kind}: {f.error}" if f.error else f.error_kind,
            hint=_HINTS.get(f.error_kind, _HINTS["unavailable"]),
            metrics=metrics,
            cause=f"imap_{f.error_kind}",
        )
    if f.last_poll_at is None or now - f.last_poll_at > STALE_AFTER:
        return CheckResult(
            KEY,
            "warn",
            "Ящик давно не опрашивался",
            hint=hosting_hint(
                "Опрос ящика идёт задачей фонового обработчика (воркер CRM) раз в 2 минуты",
                "Запустить crm-worker вместе с ансамблем",
            ),
            metrics=metrics,
            cause="queue_stuck",
        )
    return CheckResult(KEY, "ok", f"Ящик опрашивается; ждут разбора: {f.waiting}", metrics=metrics)

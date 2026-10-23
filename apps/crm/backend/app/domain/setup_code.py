"""Одноразовый код мастера первого запуска (docs/audits/crm/2026-10-12-admin-console-scope.md §4).

Код живёт в памяти процесса api: выдаётся, пока нет ни одного активного админа, действует
24 ч, после создания админа гасится навсегда. Перезапуск api выдаёт новый код (старый
исчезает вместе с процессом) — это безопасно: код нужен только до появления админа.
Перебор ограничен: после `max_failures` неверных кодов проверка закрыта на `lockout`.
"""

import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.domain.errors import Reason, ValidationFailedError

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без 0/O/1/I — код читают из логов глазами
CODE_LENGTH = 16
CODE_TTL = timedelta(hours=24)
MAX_FAILURES = 10
LOCKOUT = timedelta(minutes=15)


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize(code: str) -> str:
    """Регистр, пробелы и дефисы при вводе не важны."""
    return "".join(ch for ch in code.upper() if ch.isalnum())


@dataclass(slots=True)
class SetupCodeGate:
    """Состояние одного кода: выдача, проверка с ограничением перебора, гашение."""

    code: str | None = None
    issued_at: datetime | None = None
    failures: int = 0
    locked_until: datetime | None = None
    max_failures: int = MAX_FAILURES
    ttl: timedelta = CODE_TTL
    lockout: timedelta = LOCKOUT

    def issue(self, now: datetime) -> str:
        self.code, self.issued_at = new_code(), now
        self.failures, self.locked_until = 0, None
        return self.code

    def is_valid(self, now: datetime) -> bool:
        return (
            self.code is not None and self.issued_at is not None and now - self.issued_at < self.ttl
        )

    def verify(self, candidate: str, now: datetime) -> None:
        """Ошибка 422 с причиной; успех не гасит код — гасит `consume` после создания админа."""
        if self.locked_until is not None and now < self.locked_until:
            raise ValidationFailedError(
                "too many wrong codes", reason=Reason.SETUP_LOCKED, field="code"
            )
        if self.code is None or self.issued_at is None:
            raise ValidationFailedError(
                "no setup code issued", reason=Reason.SETUP_CODE_EXPIRED, field="code"
            )
        if not secrets.compare_digest(normalize(candidate), self.code):
            self.failures += 1
            if self.failures >= self.max_failures:
                self.locked_until, self.failures = now + self.lockout, 0
            raise ValidationFailedError(
                "wrong setup code", reason=Reason.SETUP_CODE_INVALID, field="code"
            )
        if not self.is_valid(now):
            raise ValidationFailedError(
                "setup code expired", reason=Reason.SETUP_CODE_EXPIRED, field="code"
            )

    def consume(self) -> None:
        self.code, self.issued_at = None, None

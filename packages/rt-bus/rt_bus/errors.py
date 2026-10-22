"""Исключения rt_bus: все наследуют `RtBusError`."""

from __future__ import annotations


class RtBusError(Exception):
    """Базовое исключение библиотеки."""


class ConfigError(RtBusError):
    """Неверная или неполная настройка: нет каталога контрактов, файла подписок, неверный параметр."""


class NotInTransactionError(RtBusError):
    """`publish` вызван вне транзакции: событие не может быть атомарным с изменением (runbook §2)."""


class InTransactionError(RtBusError):
    """Доставка вызвана внутри транзакции: HTTP не идёт под внешней транзакцией (соединение и блокировки)."""


class EventValidationError(RtBusError):
    """Конверт или `data` не по схеме у издателя (строгая проверка до записи в outbox)."""

    def __init__(self, message: str, errors: list[str] | None = None) -> None:
        super().__init__(message if not errors else f"{message}: {'; '.join(errors[:5])}")
        self.errors = list(errors or [])


class UnknownEventTypeError(EventValidationError):
    """Тип события не по формату L2 или для него нет схемы в каталоге контрактов."""


class SubscriptionsError(ConfigError):
    """Файл подписок не читается или не по схеме L5."""

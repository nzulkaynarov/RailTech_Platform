"""Стадии жизненного цикла лида и источники переходов (SPEC §6.1, BUSINESS.md §5)."""

from enum import StrEnum


class Stage(StrEnum):
    NEW = "new"
    ENGAGED = "engaged"
    QUALIFIED = "qualified"
    HANDOFF = "handoff"
    IN_PROGRESS = "in_progress"
    WON = "won"
    CUSTOMER = "customer"
    LOST = "lost"
    UNRESPONSIVE = "unresponsive"


class TransitionSource(StrEnum):
    QUALIFIER = "qualifier"
    TRIGGER = "trigger"
    USER = "user"
    TIMER = "timer"
    SYSTEM = "system"
    # Событие ERP (ADR-0022): никогда не меняет стадию лида, в `stage_transitions` не пишется.
    ERP = "erp"


class OwnerMode(StrEnum):
    BOT = "bot"
    HUMAN = "human"
    PAUSED = "paused"

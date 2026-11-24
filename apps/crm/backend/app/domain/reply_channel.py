"""Канал ответа менеджера лиду (CH-1): чистое правило, экран только показывает результат.

Порядок: канал последнего сообщения клиента, если он ещё доступен; иначе любой доступный
(Telegram при согласии, затем кабинет); иначе почта, если клиент писал сам или дал согласие;
иначе отказ с причиной.
"""

from dataclasses import dataclass
from typing import Final, Literal

ReplyChannel = Literal["telegram", "cabinet", "email"]
ReplyBlocked = Literal["no_consent", "phone_only", "no_contact"]

# Источники, где клиент сам оставил адрес почты и ждёт ответа: согласие на письмо не нужно.
EMAIL_INITIATED_SOURCES: Final = frozenset({"web", "email"})


@dataclass(frozen=True, slots=True)
class ReplyFacts:
    has_telegram: bool  # открытая беседа с чатом Telegram
    has_cabinet: bool  # открытая беседа кабинета с компанией ERP
    has_consent: bool
    email: str | None
    has_phone: bool
    source: str
    last_inbound: str | None  # канал последнего сообщения клиента


@dataclass(frozen=True, slots=True)
class ReplyVia:
    channel: ReplyChannel | None
    blocked: ReplyBlocked | None = None


def reply_via(facts: ReplyFacts) -> ReplyVia:
    telegram = facts.has_telegram and facts.has_consent
    cabinet = facts.has_cabinet
    if facts.last_inbound == "telegram" and telegram:
        return ReplyVia("telegram")
    if facts.last_inbound == "cabinet" and cabinet:
        return ReplyVia("cabinet")
    if telegram:
        return ReplyVia("telegram")
    if cabinet:
        return ReplyVia("cabinet")
    if (facts.email or "").strip() and (
        facts.source in EMAIL_INITIATED_SOURCES or facts.has_consent
    ):
        return ReplyVia("email")
    if facts.has_telegram:
        return ReplyVia(None, "no_consent")
    if facts.has_phone:
        return ReplyVia(None, "phone_only")
    return ReplyVia(None, "no_contact")

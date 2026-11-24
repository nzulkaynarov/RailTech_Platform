"""Канал ответа менеджера лиду (CH-1): чистое правило, экран только показывает результат.

Порядок: канал последнего сообщения клиента, если он ещё доступен; иначе любой доступный
(Telegram при согласии, затем кабинет); иначе почта, если клиент писал сам или дал согласие;
иначе отказ с причиной.
"""

from dataclasses import dataclass
from typing import Final, Literal

ReplyChannel = Literal["telegram", "cabinet", "email"]
ReplyBlocked = Literal[
    "no_consent", "no_email_consent", "email_undeliverable", "phone_only", "no_contact"
]

# Источник, где клиент сам оставил адрес и ждёт ответа: согласие на письмо не нужно. «email» —
# так только при настоящем входящем письме (`ReplyFacts.inbound_mail`): менеджер может
# выбрать «Почта» и при ручном создании, это не «клиент написал первым».
EMAIL_INITIATED_SOURCES: Final = frozenset({"web"})


@dataclass(frozen=True, slots=True)
class ReplyFacts:
    has_telegram: bool  # открытая беседа с чатом Telegram
    has_cabinet: bool  # открытая беседа кабинета с компанией ERP
    has_consent: bool
    email: str | None
    has_phone: bool
    source: str
    last_inbound: str | None  # канал последнего сообщения клиента
    inbound_mail: bool = False  # у лида есть настоящее входящее письмо клиента
    email_blocked: bool = False  # адрес не доставляет (отчёт о недоставке)


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
    if (facts.email or "").strip():
        if facts.email_blocked:
            return ReplyVia(None, "email_undeliverable")
        initiated = facts.source in EMAIL_INITIATED_SOURCES or (
            facts.source == "email" and facts.inbound_mail
        )
        if initiated or facts.has_consent:
            return ReplyVia("email")
        if not facts.has_telegram:
            return ReplyVia(None, "no_email_consent")
    if facts.has_telegram:
        return ReplyVia(None, "no_consent")
    if facts.has_phone:
        return ReplyVia(None, "phone_only")
    return ReplyVia(None, "no_contact")

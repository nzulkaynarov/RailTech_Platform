"""«Отметить за контрагента» (A1 волны 18a): решение клиента по КП, которое записал сотрудник по подтверждению клиента.

Штатный второй путь рядом с онлайн-решением клиента (кабинет, публичная ссылка) — как «Mark as Accepted» в Zoho,
«Mark as signed» в HubSpot, `Quote.Status = Accepted` в Salesforce, «Confirm» в Odoo. Атрибуция одна на все шаги
(`docs/research/2026-11-02-flexibility/3-on-behalf.md` §4.1): канал, кто со стороны клиента, когда, комментарий и
подтверждающий файл клиента — письмо, переписка, скан (обязателен: решение юриста 2026-11-02, устного «да» мало); кто и
когда записал — система. Решение идёт через ТО ЖЕ ядро, что онлайн-акцепт и отказ
(`lifecycle_accept.perform_quote_acceptance` / `perform_quote_rejection` с аргументом `on_behalf`).
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import Any, Optional

from django.utils import timezone

#: Как клиент сообщил решение (контракт `OnBehalfChannel` BFF и `RecordedByStaff.channel` события).
CHANNELS = ("phone", "email", "messenger", "in_person", "paper")

CHANNEL_WORDS = {
    "phone": "телефон",
    "email": "почта",
    "messenger": "мессенджер",
    "in_person": "лично",
    "paper": "бумага",
}

PERSON_MAX = 200
COMMENT_MAX = 2000


def staff_name(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or "").strip() or user.email


@dataclass(frozen=True)
class OnBehalf:
    """Атрибуция решения контрагента, записанного сотрудником."""

    recorded_by: Any
    channel: str
    counterparty_person: str
    occurred_on: datetime.date
    comment: str
    evidence_attachment_id: Optional[int] = None
    evidence_name: str = ""

    def meta(self, decision: str) -> dict:
        """Снимок на КП (`Quote.client_decision_meta`)."""
        return {
            "decision": decision,
            "channel": self.channel,
            "counterparty_person": self.counterparty_person,
            "occurred_on": self.occurred_on.isoformat(),
            "comment": self.comment,
            "recorded_by_id": getattr(self.recorded_by, "pk", None),
            "recorded_by_name": staff_name(self.recorded_by),
            "recorded_at": timezone.now().isoformat(),
            "evidence_attachment_id": self.evidence_attachment_id,
            "evidence_name": self.evidence_name,
        }

    def event_ref(self) -> dict:
        """`QuoteOutcome.recorded_by_staff` события шины."""
        return {
            "staff_name": staff_name(self.recorded_by),
            "channel": self.channel,
            "counterparty_person": self.counterparty_person,
            "occurred_on": self.occurred_on.isoformat(),
        }

    def journal(self) -> dict:
        """`event_params.on_behalf` журнала (`ActivityLog`): значок «Отмечено сотрудником» в истории."""
        return {
            "channel": self.channel,
            "counterparty_person": self.counterparty_person,
            "occurred_on": self.occurred_on.isoformat(),
            "evidence_attachment_id": self.evidence_attachment_id,
            "evidence_name": self.evidence_name,
        }

    def words(self) -> str:
        """«по подтверждению клиента: Иванов И. (почта)» — для журнала и уведомления на русском."""
        return f"по подтверждению клиента: {self.counterparty_person} ({CHANNEL_WORDS.get(self.channel, self.channel)})"

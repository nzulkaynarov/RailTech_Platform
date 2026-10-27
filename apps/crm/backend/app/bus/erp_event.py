"""Событие ERP, принятое с шины, в виде, удобном обработчикам CRM.

Модели `data` — сгенерированные из JSON Schema (`rt_contracts.events.erp`), ручной копии схем в CRM
нет. `ErpEvent` добавляет к ним то, что в шине лежит в конверте: имя (`quote.sent`) и момент события
(`time` конверта = прежнее `occurred_at`).
"""

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from pydantic import BaseModel, RootModel
from rt_bus import Event
from rt_bus.envelope import parse_time
from rt_contracts.events import TYPES
from rt_contracts.events.erp import Actor, DealRef

ERP_DOMAIN_PREFIX: Final = "uz.railtech.erp."
CODE_TYPE: Final = "uz.railtech.erp.quote.acceptance_code_requested.v1"
#: Приглашение в кабинет через Telegram (D1-9): ERP в Telegram не пишет — доставляет бот CRM,
#: inline.
INVITE_TYPE: Final = "uz.railtech.erp.invite.requested.v1"
INLINE_TYPES: Final = frozenset({CODE_TYPE, INVITE_TYPE})
#: Типы ERP не для CRM: КП на одобрение директором адресовано EDS (EDS-03), в нём
#: себестоимость и маржа; CRM на него не подписана (`packages/contracts/bus/subscriptions.yaml`)
#: и обработчика не регистрирует.
NOT_FOR_CRM: Final = frozenset({"uz.railtech.erp.quote.ready_for_approval.v1"})
_NAME: Final = re.compile(r"^uz\.railtech\.erp\.(?P<name>[a-z_]+\.[a-z_]+)\.v\d+$")


def plain(value: Any) -> Any:
    """Значение поля без обёртки `RootModel` (`Amount`, `Currency`, …) и без enum."""
    if isinstance(value, RootModel):
        return value.root
    return getattr(value, "value", value)


def erp_types() -> list[str]:
    """Типы событий ERP, которые CRM принимает через очередь (код акцепта и приглашение — inline,
    отдельно)."""
    return sorted(
        t
        for t in TYPES
        if t.startswith(ERP_DOMAIN_PREFIX) and t not in INLINE_TYPES and t not in NOT_FOR_CRM
    )


@dataclass(frozen=True, slots=True)
class ErpEvent:
    """Событие ERP: `event` — прежнее имя без домена и версии, `data` — модель типа."""

    id: str
    event: str
    occurred_at: datetime
    data: Any

    @property
    def erp_company_id(self) -> int:
        return int(self.data.erp_company_id)

    @property
    def crm_client_id(self) -> int:
        return int(self.data.crm_client_id)

    @property
    def deal(self) -> DealRef | None:
        # У `invite.requested` сделки нет вовсе (поле не входит в схему типа).
        deal: DealRef | None = getattr(self.data, "deal", None)
        return deal

    @property
    def actor(self) -> Actor:
        actor: Actor = self.data.actor
        return actor

    @property
    def payload(self) -> Any:
        return self.data.payload


def parse_erp_event(event: Event) -> ErpEvent:
    """Конверт шины → `ErpEvent`; тип не из каталога ERP или `data` не по модели — `ValueError`."""
    match = _NAME.fullmatch(event.type)
    model: type[BaseModel] | None = TYPES.get(event.type)
    if match is None or model is None:
        raise ValueError(f"not an ERP event type: {event.type}")
    data = model.model_validate(event.data)
    return ErpEvent(event.id, match["name"], parse_time(event.time), data)

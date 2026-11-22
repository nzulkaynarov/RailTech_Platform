"""«Вы ждёте других» (ГЛ-1): что сотрудник передал и ждёт от другого, и напоминание (eds.yaml: WaitingItem…)."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import PersonRef

WaitingKind = Literal["letter_signature", "approval", "instruction"]
# Напоминание по тому же объекту не чаще раза в час (иначе «Напомнить» превращается в спам).
REMIND_INTERVAL = dt.timedelta(hours=1)


class WaitingItem(BaseModel):
    kind: WaitingKind
    object_id: uuid.UUID
    number: str | None
    title: str
    # Кто должен ответить; `None` — шаг «любой с правом» или подписанта нет: тогда `waiting_label`.
    waiting_on: PersonRef | None
    waiting_label: str | None
    since: dt.datetime
    due: dt.date | None
    # `None` — напомнить можно сейчас; иначе момент, с которого можно (после прошлого напоминания).
    remind_available_at: dt.datetime | None
    remindable: bool


class WaitingList(BaseModel):
    items: list[WaitingItem]
    # Один из списков обрезан по пределу: «показаны не все»
    more: bool


class RemindOut(BaseModel):
    reminded_at: dt.datetime

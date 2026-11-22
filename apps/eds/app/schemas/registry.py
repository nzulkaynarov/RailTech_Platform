"""Схемы реестра «Все документы» (eds.yaml: RegistryItem, RegistryPage)."""

import datetime as dt
import uuid
from enum import StrEnum

from pydantic import BaseModel

from app.schemas.common import ErpLinks, LetterSender, Money, PersonRef


class RegistryStage(StrEnum):
    """`open` — документ ждёт чьего-то действия (в том числе контрагента), `done` — путь завершён (eds.yaml 0.15.0)."""

    OPEN = "open"
    DONE = "done"


class RegistryKind(StrEnum):
    LETTER_IN = "letter_in"
    LETTER_OUT = "letter_out"
    QUOTE = "quote"
    MEMO = "memo"
    APPLICATION = "application"
    REPORT = "report"
    CONTRACT = "contract"  # D2-5: договоры, счета и акты проектов — проекция по событиям ERP
    INVOICE = "invoice"
    ACT = "act"


class RegistryItem(BaseModel):
    kind: RegistryKind
    id: uuid.UUID
    number: str | None
    #: Номер до перенумерации (СЦ-5); по нему же находит реестр и старая ссылка
    previous_number: str | None = None
    title: str
    status: str
    registered_at: dt.datetime
    responsible: PersonRef | None
    client: LetterSender | None
    links: ErpLinks
    amount: Money | None
    #: Исходящее письмо с почтой адресата не ушло и отправку не сняли (СЦ-1): строка остаётся в «Исходящих»
    undelivered: bool = False
    #: Исходящее письмо передано на подпись и не подписано (СЦ-8); у остальных видов — false
    awaiting_signature: bool = False


class RegistryPage(BaseModel):
    items: list[RegistryItem]
    next_cursor: str | None

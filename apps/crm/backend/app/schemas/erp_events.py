"""Схемы событий ERP → CRM (M3-CRM-04, CONTRACTS §3, packages/contracts/events.schema.json; FIX-35).

Конверт разбирается ДИСКРИМИНИРОВАННЫМИ моделями по `event`: у каждого из 22 типов события свой
класс конверта с типизированным `payload` (`parse_event`). Читатель терпимый: лишние поля в
конверте и в телах игнорируются (`extra="ignore"`) — новое необязательное поле ERP не должно
давать отказ и ретраи; обязательные поля, типы и перечисления — как в схеме. Неизвестный тип
события в этот разбор не попадает: приёмник записывает его как «пропущено» (`is_known_event`)
и отвечает 200.
"""

import re
from datetime import date, datetime
from typing import Annotated, Any, Literal, Union, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    TypeAdapter,
    field_validator,
    model_validator,
)

EventType = Literal[
    "request.created",
    "deal.stage_changed",
    "quote.sent",
    "quote.viewed",
    "quote.accepted",
    "quote.rejected",
    "quote.acceptance_code_requested",
    "contract.signed",
    "invoice.issued",
    "invoice.paid",
    "invoice.overdue",
    "delivery.status_changed",
    "delivery.eta_changed",
    "act.issued",
    "act.accepted",
    "act.returned",
    "deal.won",
    "deal.lost",
    "document.created",
    "invite.sent",
    "delivery.line_accepted",
    "delivery.line_disputed",
]

DealStage = Literal[
    "request",
    "quoting",
    "quote_sent",
    "accepted",
    "contract",
    "invoiced",
    "paid",
    "fulfilment",
    "closing",
    "won",
    "lost",
]

AmountStr = Annotated[str, StringConstraints(pattern=r"^-?\d+\.\d{2}$")]
CurrencyStr = Annotated[str, StringConstraints(pattern=r"^[A-Z]{3}$")]


class _Tolerant(BaseModel):
    """Терпимый читатель: неизвестные поля игнорируются, обязательные — по схеме."""

    model_config = ConfigDict(extra="ignore")


class DealRef(_Tolerant):
    erp_deal_id: int
    number: str
    title: str
    stage: DealStage
    # Сумма последнего КП, отправленного клиенту; None — КП ещё не отправлялось (FIX-29).
    amount: AmountStr | None
    currency: CurrencyStr


class Actor(_Tolerant):
    type: Literal["system", "staff", "client"]
    name: str | None = None


class RequestCreated(_Tolerant):
    source: Literal["crm", "cabinet", "erp"]
    erp_request_id: int | None = None
    summary: str | None = None


class DealStageChanged(_Tolerant):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    from_: DealStage = Field(alias="from")
    to: DealStage
    reason: str | None = None


class QuoteSent(_Tolerant):
    erp_quote_id: int
    version: int = Field(ge=1)
    public_url: str
    valid_until: date | None = None
    total: AmountStr | None = None
    currency: CurrencyStr | None = None


class QuoteOutcome(_Tolerant):
    erp_quote_id: int
    version: int = Field(ge=1)
    reason: str | None = None
    # Кто из контактов принял или отклонил КП (Q-FIX22-6); нет — действие не из Cabinet.
    erp_contact_id: int | None = None
    crm_contact_id: int | None = None


#: Событие с одноразовым кодом в теле: код — секрет, в журнал, ленту и логи не попадает (Q-FIX22-1).
CODE_EVENT = "quote.acceptance_code_requested"
_CODE_PATTERN = re.compile(r"^[0-9]{4,12}$")
REDACTED = "[redacted]"


class QuoteAcceptanceCodeRequested(_Tolerant):
    """Клиент запросил код акцепта в Cabinet: код доставляет бот CRM контакту в Telegram."""

    erp_quote_id: int
    version: int = Field(ge=1)
    erp_contact_id: int
    crm_contact_id: int
    # `SecretStr`: ни `repr`, ни `model_dump` не покажут код; читает его только доставка.
    code: SecretStr
    expires_at: datetime

    @field_validator("code")
    @classmethod
    def _code_is_digits(cls, value: SecretStr) -> SecretStr:
        if not _CODE_PATTERN.fullmatch(value.get_secret_value()):
            raise ValueError("code must be 4-12 digits")
        return value


class ContractSigned(_Tolerant):
    erp_contract_id: int
    number: str | None = None
    by: Literal["client", "company", "both"]


class InvoiceEvent(_Tolerant):
    erp_invoice_id: int
    number: str
    amount: AmountStr
    currency: CurrencyStr
    due_date: date
    link: str | None = None
    erp_document_id: int | None = None


class DeliveryEvent(_Tolerant):
    line_summary: str
    line_nos: list[int] | None = None
    status: Literal["assembling", "in_transit", "ready_to_ship", "shipped", "delivered"]
    eta: date | None = None
    previous_eta: date | None = None
    tracking: str | None = None


class ActEvent(_Tolerant):
    erp_act_id: int
    number: str
    reason: str | None = None
    erp_document_id: int | None = None


class DealOutcome(_Tolerant):
    amount: AmountStr
    currency: CurrencyStr
    lost_reason: str | None = None


class DocumentCreated(_Tolerant):
    erp_document_id: int
    kind: Literal["quote", "contract", "invoice", "act", "waybill", "receipt", "other"]
    number: str
    title: str | None = None


class InviteSent(_Tolerant):
    channels: list[Literal["telegram", "email"]] = Field(min_length=1)
    erp_contact_id: int | None = None
    crm_contact_id: int | None = None


#: Тип события → статус строки в его теле (`DeliveryLineDecision.status`).
DELIVERY_LINE_EVENTS = {"delivery.line_accepted": "accepted", "delivery.line_disputed": "disputed"}


class DeliveryLineDecision(_Tolerant):
    """Решение клиента по строке поставки (FIX-22/FIX-37): принял или оспорил с замечанием."""

    line_no: int = Field(ge=1)
    title: str
    status: Literal["accepted", "disputed"]
    remark: str | None = Field(default=None, max_length=2000)
    decided_at: datetime

    @model_validator(mode="after")
    def _disputed_needs_remark(self) -> "DeliveryLineDecision":
        if self.status == "disputed" and not (self.remark or "").strip():
            raise ValueError("remark is required when status is disputed")
        return self


# ── Конверты: по классу на тип события (дискриминатор — `event`) ────────────────────────


class ErpEventEnvelope(_Tolerant):
    """Общая часть конверта по events.schema.json; тип события — подкласс с типизированным payload.

    Разбирать только через `parse_event`: он выбирает класс по `event`. `deal` обязателен у
    подклассов, где его требует схема (`allOf` в events.schema.json), и необязателен у
    `document.created` и `invite.sent`.
    """

    version: Literal[1]
    event: str
    occurred_at: datetime
    erp_company_id: int
    crm_client_id: int
    deal: DealRef | None = None
    actor: Actor
    payload: _Tolerant


class RequestCreatedEvent(ErpEventEnvelope):
    event: Literal["request.created"]
    deal: DealRef
    payload: RequestCreated


class DealStageChangedEvent(ErpEventEnvelope):
    event: Literal["deal.stage_changed"]
    deal: DealRef
    payload: DealStageChanged


class QuoteSentEvent(ErpEventEnvelope):
    event: Literal["quote.sent"]
    deal: DealRef
    payload: QuoteSent


class QuoteOutcomeEvent(ErpEventEnvelope):
    event: Literal["quote.viewed", "quote.accepted", "quote.rejected"]
    deal: DealRef
    payload: QuoteOutcome


class QuoteAcceptanceCodeRequestedEvent(ErpEventEnvelope):
    event: Literal["quote.acceptance_code_requested"]
    deal: DealRef
    payload: QuoteAcceptanceCodeRequested


class ContractSignedEvent(ErpEventEnvelope):
    event: Literal["contract.signed"]
    deal: DealRef
    payload: ContractSigned


class InvoiceEnvelope(ErpEventEnvelope):
    event: Literal["invoice.issued", "invoice.paid", "invoice.overdue"]
    deal: DealRef
    payload: InvoiceEvent


class DeliveryEnvelope(ErpEventEnvelope):
    event: Literal["delivery.status_changed", "delivery.eta_changed"]
    deal: DealRef
    payload: DeliveryEvent


class ActEnvelope(ErpEventEnvelope):
    event: Literal["act.issued", "act.accepted", "act.returned"]
    deal: DealRef
    payload: ActEvent


class DealOutcomeEvent(ErpEventEnvelope):
    event: Literal["deal.won", "deal.lost"]
    deal: DealRef
    payload: DealOutcome


class DocumentCreatedEvent(ErpEventEnvelope):
    event: Literal["document.created"]
    payload: DocumentCreated


class InviteSentEvent(ErpEventEnvelope):
    event: Literal["invite.sent"]
    payload: InviteSent


class DeliveryLineEvent(ErpEventEnvelope):
    """`delivery.line_*`: сделка обязательна, решает клиент, статус тела совпадает с типом
    события.
    """

    event: Literal["delivery.line_accepted", "delivery.line_disputed"]
    deal: DealRef
    payload: DeliveryLineDecision

    @model_validator(mode="after")
    def _decision_matches_event(self) -> "DeliveryLineEvent":
        if self.actor.type != "client":
            raise ValueError(f"{self.event} requires actor.type=client")
        if self.payload.status != DELIVERY_LINE_EVENTS[self.event]:
            raise ValueError(f"{self.event} does not match payload status {self.payload.status}")
        return self


ErpEvent = Annotated[
    Union[  # noqa: UP007 — pydantic: дискриминированный Union
        RequestCreatedEvent,
        DealStageChangedEvent,
        QuoteSentEvent,
        QuoteOutcomeEvent,
        QuoteAcceptanceCodeRequestedEvent,
        ContractSignedEvent,
        InvoiceEnvelope,
        DeliveryEnvelope,
        ActEnvelope,
        DealOutcomeEvent,
        DocumentCreatedEvent,
        InviteSentEvent,
        DeliveryLineEvent,
    ],
    Field(discriminator="event"),
]

_EVENT_ADAPTER: TypeAdapter[ErpEvent] = TypeAdapter(ErpEvent)

#: Типы событий, которые CRM умеет разбирать (= `EventType`; тест сверяет с events.schema.json).
KNOWN_EVENTS: frozenset[str] = frozenset(get_args(EventType))


def redact_secrets(data: dict[str, Any], event_type: str | None = None) -> dict[str, Any]:
    """Копия тела события без секретов: `payload.code` кода акцепта заменён на `[redacted]`.

    Событие с кодом — по `event` в теле или по заголовку `X-Event-Type` (`event_type`): тело с
    расхождением типа тоже не должно унести код в журнал. Только для журнала: разбор и доставка
    работают с исходным телом. Остальные события — без изменений (то же тело).
    """
    payload = data.get("payload")
    secret = CODE_EVENT in (data.get("event"), event_type)
    if not secret or not isinstance(payload, dict) or "code" not in payload:
        return data
    return {**data, "payload": {**payload, "code": REDACTED}}


def is_known_event(name: object) -> bool:
    return isinstance(name, str) and name in KNOWN_EVENTS


def parse_event(data: object) -> ErpEvent:
    """Тело события → конверт нужного класса; `ValidationError` — тело не по схеме."""
    return _EVENT_ADAPTER.validate_python(data)


class ErpWebhookReceipt(BaseModel):
    status: Literal["ok"] = "ok"
    duplicate: bool = False

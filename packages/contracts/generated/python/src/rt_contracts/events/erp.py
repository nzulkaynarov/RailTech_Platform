# Сгенерировано scripts/gen_python.py из packages/contracts/events/ — не править руками (make contracts).

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AnyUrl, AwareDatetime, BaseModel, ConfigDict, Field, RootModel


class ActAcceptedV1(BaseModel):
    """
    Тип uz.railtech.erp.act.accepted.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события act.accepted из events.schema.json без version, event, occurred_at. Что делает CRM: лента.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: ActEvent


class ActEvent(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    erp_act_id: int
    number: str
    reason: str | None = None
    erp_document_id: int | None = None


class ActIssuedV1(BaseModel):
    """
    Тип uz.railtech.erp.act.issued.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события act.issued из events.schema.json без version, event, occurred_at. Что делает CRM: бот CRM: «акт ждёт подтверждения».
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: ActEvent


class ActReturnedV1(BaseModel):
    """
    Тип uz.railtech.erp.act.returned.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события act.returned из events.schema.json без version, event, occurred_at. Что делает CRM: лента; уведомление ответственному.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: ActEvent


class Actor(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    type: Type
    name: str | None = None


class Amount(RootModel[str]):
    root: Annotated[str, Field(pattern="^-?\\d+\\.\\d{2}$")]


class By(StrEnum):
    client = "client"
    company = "company"
    both = "both"


class CalcZone(StrEnum):
    """
    Зона визы расчёта: goods — товары и склад (снабженец), services — услуги (гл. инженер); ADR-0012 п. 6
    """

    goods = "goods"
    services = "services"


class Channel(StrEnum):
    telegram = "telegram"
    email = "email"


class ClientActor(BaseModel):
    """
    Действие клиента в Cabinet (Actor с type=client)
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    type: Literal["client"]
    name: str | None = None


class ContractSigned(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    erp_contract_id: int
    number: str | None = None
    by: By


class ContractSignedV1(BaseModel):
    """
    Тип uz.railtech.erp.contract.signed.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события contract.signed из events.schema.json без version, event, occurred_at. Что делает CRM: лента.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: ContractSigned


class ContractStatusChanged(BaseModel):
    """
    Договор сменил статус по SPEC-v3 §2.4 (D2-5). Договор подписывают вне платформы (у оператора ЭДО): в ERP фиксируются статусы и скан. `project` — проект (флаг `sent_to_client` — ушёл ли клиенту на согласование редакции), `client_agreed` — согласован клиентом, `issued_at_operator` — выставлен у оператора, `signed` — подписан (прикреплён скан), `rejected` — отклонён клиентом, `cancelled` — отменён. Событие порождает каждый переход и создание проекта договора.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_contract_id: int
    number: str
    status: Status
    sent_to_client: bool
    amount: Amount | None = None
    currency: Currency | None = None
    reason: str | None = None
    """
    Причина отклонения клиентом (для `rejected`)
    """


class ContractStatusChangedV1(BaseModel):
    """
    Тип uz.railtech.erp.contract.status_changed.v1, источник rt://erp. Поле data конверта (envelope.v1.json). Новый тип D2-5 (SPEC-v3 §2.4): договор подписывают вне платформы, ERP фиксирует статусы «Проект», «Согласован клиентом», «Выставлен у оператора», «Подписан (скан)», «Отклонён». Что делает EDS: проекция документа проекта в реестре «Все документы». CRM тип не доставляется (`NOT_FOR_CRM`).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: ContractStatusChanged


class Currency(RootModel[str]):
    root: Annotated[str, Field(pattern="^[A-Z]{3}$")]


class DealLostV1(BaseModel):
    """
    Тип uz.railtech.erp.deal.lost.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события deal.lost из events.schema.json без version, event, occurred_at. Что делает CRM: зеркало сделки CRM → lost; стадия лида не меняется (CRM ADR-0022).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: DealOutcome


class DealOutcome(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    amount: Amount
    currency: Currency
    lost_reason: str | None = None


class DealRef(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    erp_deal_id: int
    number: str
    title: str
    stage: DealStage
    amount: Amount | None
    """
    Сумма последней версии КП, отправленной клиенту; null — КП клиенту ещё не отправлялось (черновики и КП на согласовании не учитываются)
    """
    currency: Currency


class DealStage(StrEnum):
    request = "request"
    quoting = "quoting"
    quote_sent = "quote_sent"
    accepted = "accepted"
    contract = "contract"
    invoiced = "invoiced"
    paid = "paid"
    fulfilment = "fulfilment"
    closing = "closing"
    won = "won"
    lost = "lost"


class DealStageChanged(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    from_: Annotated[DealStage, Field(alias="from")]
    to: DealStage
    reason: str | None = None


class DealStageChangedV1(BaseModel):
    """
    Тип uz.railtech.erp.deal.stage_changed.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события deal.stage_changed из events.schema.json без version, event, occurred_at. Что делает CRM: лента; external_stage в CRM.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: DealStageChanged


class DealWonV1(BaseModel):
    """
    Тип uz.railtech.erp.deal.won.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события deal.won из events.schema.json без version, event, occurred_at. Что делает CRM: зеркало сделки CRM → won; стадия лида не меняется (CRM ADR-0022).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: DealOutcome


class DeliveryEtaChangedV1(BaseModel):
    """
    Тип uz.railtech.erp.delivery.eta_changed.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события delivery.eta_changed из events.schema.json без version, event, occurred_at. Что делает CRM: бот CRM по политике «сообщать о сдвигах».
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: DeliveryEvent


class DeliveryEvent(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    line_summary: str
    """
    Краткое описание строк, к которым относится событие
    """
    line_nos: list[LineNo] | None = None
    status: Status1
    eta: date | None = None
    previous_eta: date | None = None
    tracking: str | None = None


class DeliveryLineAcceptedV1(BaseModel):
    """
    Тип uz.railtech.erp.delivery.line_accepted.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события delivery.line_accepted из events.schema.json без version, event, occurred_at. Что делает CRM: лента (FIX-37); actor.type=client.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: ClientActor
    payload: DeliveryLineDecision


class DeliveryLineDecision(BaseModel):
    """
    Решение клиента по строке поставки в Cabinet (FIX-22): принял или оспорил с замечанием
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    line_no: Annotated[int, Field(ge=1)]
    title: str
    status: Status2
    remark: Annotated[str | None, Field(max_length=2000)] = None
    """
    Замечание клиента; обязательно при disputed
    """
    decided_at: AwareDatetime


class DeliveryLineDisputedV1(BaseModel):
    """
    Тип uz.railtech.erp.delivery.line_disputed.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события delivery.line_disputed из events.schema.json без version, event, occurred_at. Что делает CRM: лента; уведомление ответственному (FIX-37); actor.type=client, замечание обязательно.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: ClientActor
    payload: DeliveryLineDecision


class DeliveryStatusChangedV1(BaseModel):
    """
    Тип uz.railtech.erp.delivery.status_changed.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события delivery.status_changed из events.schema.json без version, event, occurred_at. Что делает CRM: бот CRM по политике «сообщать о сдвигах».
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: DeliveryEvent


class DocumentCreated(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    erp_document_id: int
    kind: Kind
    number: str
    title: str | None = None


class DocumentCreatedV1(BaseModel):
    """
    Тип uz.railtech.erp.document.created.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события document.created из events.schema.json без version, event, occurred_at. Что делает CRM: индекс документов клиента в CRM (без файла).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef | None = None
    actor: Actor
    payload: DocumentCreated


class InviteRequested(BaseModel):
    """
    Приглашение контакта в Cabinet через бот CRM (D1-9). Рабочей ссылки и токенов нет: контакт входит в Mini App по своему Telegram-аккаунту (initData), поэтому событие не секретно.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    channel: Literal["telegram"]
    erp_contact_id: int
    crm_contact_id: int
    language: Language | None = None
    """
    Язык контакта в ERP; бот CRM берёт язык лида, если он известен
    """


class InviteRequestedV1(BaseModel):
    """
    Тип uz.railtech.erp.invite.requested.v1, источник rt://erp. Поле data конверта (envelope.v1.json). ERP в Telegram не пишет (бот принадлежит CRM): сотрудник или передача из CRM пригласили контакта в канал telegram — ERP публикует событие, бот CRM присылает контакту сообщение с кнопкой «Открыть кабинет» (Mini App; вход по Telegram-аккаунту контакта, секретов в событии нет). Что делает CRM: доставка ботом; итог (отправлено или причина отказа словами) виден менеджеру в карточке клиента. ERP публикует событие только контакту с crm_contact_id и привязанным telegram_user_id (D1-9).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    actor: Actor
    payload: InviteRequested


class InviteSent(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    channels: Annotated[list[Channel], Field(min_length=1)]
    erp_contact_id: int | None = None
    crm_contact_id: int | None = None


class InviteSentV1(BaseModel):
    """
    Тип uz.railtech.erp.invite.sent.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события invite.sent из events.schema.json без version, event, occurred_at. Что делает CRM: лента.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef | None = None
    actor: Actor
    payload: InviteSent


class InvoiceEvent(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    erp_invoice_id: int
    number: str
    amount: Amount
    currency: Currency
    due_date: date
    link: AnyUrl | None = None
    """
    Ссылка на счёт в Cabinet
    """
    erp_document_id: int | None = None


class InvoiceIssuedV1(BaseModel):
    """
    Тип uz.railtech.erp.invoice.issued.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события invoice.issued из events.schema.json без version, event, occurred_at. Что делает CRM: бот CRM: «счёт выставлен».
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: InvoiceEvent


class InvoiceOverdueV1(BaseModel):
    """
    Тип uz.railtech.erp.invoice.overdue.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события invoice.overdue из events.schema.json без version, event, occurred_at. Что делает CRM: напоминание шлёт ERP письмом; бот CRM дублирует по политике.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: InvoiceEvent


class InvoicePaidV1(BaseModel):
    """
    Тип uz.railtech.erp.invoice.paid.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события invoice.paid из events.schema.json без version, event, occurred_at. Что делает CRM: лента; бот по политике.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: InvoiceEvent


class Kind(StrEnum):
    quote = "quote"
    contract = "contract"
    invoice = "invoice"
    act = "act"
    waybill = "waybill"
    receipt = "receipt"
    other = "other"


class Language(StrEnum):
    """
    Язык контакта в ERP; бот CRM берёт язык лида, если он известен
    """

    ru = "ru"
    uz = "uz"
    en = "en"


class LineNo(RootModel[int]):
    root: Annotated[int, Field(ge=1)]


class QuoteAcceptanceCodeRequested(BaseModel):
    """
    Клиент запросил код акцепта в Cabinet, контакт в Telegram: код доставляет бот CRM (Q-FIX22-1). ERP шлёт событие только контакту с crm_contact_id и telegram; иначе код уходит письмом ERP
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_quote_id: int
    version: Annotated[int, Field(ge=1)]
    erp_contact_id: int
    crm_contact_id: int
    code: Annotated[str, Field(pattern="^[0-9]{4,12}$")]
    """
    Одноразовый код — секрет: не хранить и не логировать в CRM
    """
    expires_at: AwareDatetime


class QuoteAcceptanceCodeRequestedV1(BaseModel):
    """
    Тип uz.railtech.erp.quote.acceptance_code_requested.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события quote.acceptance_code_requested из events.schema.json без version, event, occurred_at. Что делает CRM: бот CRM присылает код контакту в Telegram (Q-FIX22-1). payload.code — секрет: подписчик не пишет его в ленту, журнал, inbox-лог и логи.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: QuoteAcceptanceCodeRequested


class QuoteAcceptedV1(BaseModel):
    """
    Тип uz.railtech.erp.quote.accepted.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события quote.accepted из events.schema.json без version, event, occurred_at. Что делает CRM: лента; уведомление ответственному.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: QuoteOutcome


class QuoteOutcome(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    erp_quote_id: int
    version: Annotated[int, Field(ge=1)]
    reason: str | None = None
    erp_contact_id: int | None = None
    """
    Контакт клиента, который принял или отклонил КП (Q-FIX22-6); нет — действие не из Cabinet
    """
    crm_contact_id: int | None = None
    """
    Тот же контакт в CRM, если сопоставлен
    """


class QuoteReadyForApproval(BaseModel):
    """
    Снимок КП для маршрута одобрения в EDS (EDS-03): суммы, маржа, визы, порог маржи резолюции
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_quote_id: int
    number: Annotated[str, Field(max_length=64, min_length=1)]
    """
    КП-ГГГГ/NNN
    """
    version: Annotated[int, Field(ge=1)]
    client_name: Annotated[str | None, Field(max_length=255)] = None
    total: Amount
    """
    Сумма КП с НДС
    """
    currency: Currency
    cost: Amount | None = None
    """
    Себестоимость (видит только директор)
    """
    margin_amount: Amount | None = None
    margin_pct: Annotated[str, Field(pattern="^-?\\d{1,3}(\\.\\d{1,2})?$")]
    """
    Маржа КП, % строкой; может быть отрицательной
    """
    min_margin_pct: Annotated[
        str | None, Field(pattern="^(100(\\.0{1,2})?|\\d{1,2}(\\.\\d{1,2})?)$")
    ]
    """
    Порог «маржа не ниже, %» из резолюции (letter.resolved) — снимок для показа; чек-лист EDS сверяет маржу с порогом своей резолюции (владелец поля — EDS). null — ограничения нет
    """
    required_zones: list[CalcZone]
    """
    Чьи визы нужны расчёту (по строкам КП и исполнителям резолюции)
    """
    visas: list[QuoteVisa]
    """
    Собранные визы: снабженец — goods, гл. инженер — services
    """
    due: date | None = None
    """
    Срок расчёта из резолюции
    """
    ready_at: AwareDatetime
    """
    Когда расчёт объявлен готовым
    """
    valid_until: date | None = None
    """
    Срок действия КП
    """
    eds_letter_id: UUID | None = None
    """
    Входящее письмо EDS, по резолюции которого считали (из letter.resolved)
    """


class QuoteReadyForApprovalV1(BaseModel):
    """
    Тип uz.railtech.erp.quote.ready_for_approval.v1, источник rt://erp. Поле data конверта (envelope.v1.json). Расчёт готов (все визы собраны) — ERP просит EDS открыть маршрут одобрения КП (EDS-03, runbook волны 12 §2.4, §2.5). payload — снимок для показа в маршруте и для чек-листа (визы, маржа, срок); порог маржи чек-лист берёт из резолюции EDS (владелец поля — EDS), payload.min_margin_pct — только снимок для показа. EDS коммерческого содержания не хранит сверх снимка. Новая версия КП после возврата — новое событие с version + 1. Содержит себестоимость и маржу: подписчики v1 — только eds (и platform-bff как подсказка без хранения); CRM на этот тип не подписана (bus/subscriptions.yaml). crm_client_id может быть null — компания без клиента CRM.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int | None
    """
    Клиент в CRM; null — компания не сопоставлена
    """
    deal: DealRef
    actor: Actor
    payload: QuoteReadyForApproval


class QuoteRejectedV1(BaseModel):
    """
    Тип uz.railtech.erp.quote.rejected.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события quote.rejected из events.schema.json без version, event, occurred_at. Что делает CRM: лента.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: QuoteOutcome


class QuoteSent(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    erp_quote_id: int
    version: Annotated[int, Field(ge=1)]
    public_url: AnyUrl
    valid_until: date | None = None
    total: Amount | None = None
    currency: Currency | None = None


class QuoteSentV1(BaseModel):
    """
    Тип uz.railtech.erp.quote.sent.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события quote.sent из events.schema.json без version, event, occurred_at. Что делает CRM: бот CRM: «КП готово» с кнопками.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: QuoteSent


class QuoteViewedV1(BaseModel):
    """
    Тип uz.railtech.erp.quote.viewed.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события quote.viewed из events.schema.json без version, event, occurred_at. Что делает CRM: лента.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: QuoteOutcome


class QuoteVisa(BaseModel):
    """
    Виза строки расчёта по зоне: кто и когда
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    zone: CalcZone
    by: QuoteVisaAuthor
    at: AwareDatetime


class QuoteVisaAuthor(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    crm_user_id: int | None
    """
    null — сотрудник ERP без связи с CRM
    """
    full_name: Annotated[str, Field(max_length=255, min_length=1)]


class RequestCreated(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    source: Source
    erp_request_id: int | None = None
    summary: str | None = None
    company_name: Annotated[str | None, Field(max_length=300, min_length=1)] = None
    """
    Название компании клиента (отправитель письма EDS по заявке). Необязательное, с 2026-10-26 (C1-G-7); нет — EDS показывает клиента по crm_client_id
    """
    company_inn: Annotated[str | None, Field(pattern="^\\d{9,14}$")] = None
    """
    ИНН компании клиента; публикуется, только если похож на ИНН (9–14 цифр). Необязательное (C1-G-7)
    """
    contact_name: Annotated[str | None, Field(max_length=255, min_length=1)] = None
    """
    Контактное лицо клиента по заявке (офлайн-контакт сделки, представитель клиента или основной контакт передачи из CRM). Необязательное (C1-G-7)
    """
    manager_crm_user_id: Annotated[int | None, Field(ge=1)] = None
    """
    Менеджер заявки — сотрудник CRM (crm_user_id): ответственный передачи из CRM, иначе ответственный сделки ERP с сопоставлением CRM. Нет — менеджер не назначен. Необязательное (C1-G-7)
    """


class RequestCreatedV1(BaseModel):
    """
    Тип uz.railtech.erp.request.created.v1, источник rt://erp. Поле data конверта (envelope.v1.json); прежнее тело события request.created из events.schema.json без version, event, occurred_at. Что делает CRM: лента лида в CRM; зеркало сделки open. Что делает EDS: регистрирует входящее письмо по заявке (EDS-01); отправитель — payload.company_name, company_inn и contact_name, менеджер — payload.manager_crm_user_id (необязательные, с 2026-10-26, C1-G-7; старое событие без них принимается).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания клиента в ERP
    """
    crm_client_id: int
    """
    Клиент в CRM
    """
    deal: DealRef
    actor: Actor
    payload: RequestCreated


class Source(StrEnum):
    crm = "crm"
    cabinet = "cabinet"
    erp = "erp"


class Status(StrEnum):
    project = "project"
    client_agreed = "client_agreed"
    issued_at_operator = "issued_at_operator"
    signed = "signed"
    rejected = "rejected"
    cancelled = "cancelled"


class Status1(StrEnum):
    assembling = "assembling"
    in_transit = "in_transit"
    ready_to_ship = "ready_to_ship"
    shipped = "shipped"
    delivered = "delivered"


class Status2(StrEnum):
    accepted = "accepted"
    disputed = "disputed"


class Type(StrEnum):
    system = "system"
    staff = "staff"
    client = "client"

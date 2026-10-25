# Сгенерировано scripts/gen_python.py из packages/contracts/events/ — не править руками (make contracts).

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, RootModel


class Actor(BaseModel):
    """
    Кто сделал: сотрудник (crm_user_id) или система EDS (задача, обработчик шины)
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    type: Type
    crm_user_id: int | None = None
    """
    Сотрудник при type=staff
    """


class Amount(RootModel[str]):
    root: Annotated[str, Field(pattern="^-?\\d+\\.\\d{2}$")]


class Approval(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    eds_approval_id: Uuid
    template: ApprovalTemplate
    object: ApprovalObject
    title: Annotated[str | None, Field(max_length=300, min_length=1)] = None
    """
    Тема для уведомления
    """


class ApprovalDecidedV1(BaseModel):
    """
    Тип uz.railtech.eds.approval.decided.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Решение на шаге маршрута: approve, return (на доработку), reject; comment обязателен для return и reject. route_status — состояние маршрута после решения (open — есть следующий шаг). Что делает ERP (EDS-03) для approval.object.kind = quote и закрытого маршрута: approved — ИСХ-номер outgoing_number на КП, отправка по channels разблокирована; returned — КП «На доработке» с комментарием; rejected — КП отклонено директором.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    approval: Approval
    step: Step
    decision: Decision
    comment: Annotated[str | None, Field(max_length=4000)]
    decided_by: PersonRef
    decided_at: AwareDatetime
    route_status: RouteStatus
    outgoing_number: OutgoingNumber | None
    """
    ИСХ-номер, присвоенный при одобрении КП (маршрут quote закрыт с approved); иначе null
    """
    channels: list[SendChannel] | None = None
    """
    Для одобренного КП: каналы отправки клиенту, выбранные директором
    """
    actor: Actor


class ApprovalObject(BaseModel):
    """
    Что согласуется. Документ EDS (memo, application, report) — eds_document_id и number; КП ERP (quote) — erp_quote_id, quote_number, quote_version, erp_deal_id (коммерческое содержание остаётся в ERP)
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    kind: ApprovalTemplate
    eds_document_id: Uuid | None = None
    number: RegistryNumber | None = None
    erp_quote_id: int | None = None
    quote_number: Annotated[str | None, Field(max_length=64, min_length=1)] = None
    """
    КП-ГГГГ/NNN
    """
    quote_version: Annotated[int | None, Field(ge=1)] = None
    erp_deal_id: int | None = None
    deal_number: Annotated[str | None, Field(max_length=64)] = None


class ApprovalRequestedV1(BaseModel):
    """
    Тип uz.railtech.eds.approval.requested.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Открыт маршрут (или новый круг после возврата): первый шаг и кто решает. Для КП — после uz.railtech.erp.quote.ready_for_approval.v1. Подписчики v1: platform-bff (колокольчик, «Моя очередь»).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    approval: Approval
    step: Step
    actor: Actor


class ApprovalTemplate(StrEnum):
    """
    Шаблон маршрута (runbook §2.5): memo — директор, затем бухгалтер, если указана сумма; quote — директор с чек-листом; application, report — директор
    """

    memo = "memo"
    application = "application"
    report = "report"
    quote = "quote"


class Assignee(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    crm_user_id: int
    zone: Zone


class Currency(RootModel[str]):
    root: Annotated[str, Field(pattern="^[A-Z]{3}$")]


class Decision(StrEnum):
    approve = "approve"
    return_ = "return"
    reject = "reject"


class Document(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    eds_document_id: Uuid
    kind: DocumentKind
    number: RegistryNumber
    subject: Annotated[str, Field(max_length=300, min_length=1)]
    author: PersonRef
    addressee: PersonRef | None = None
    registered_at: AwareDatetime
    amount: Money | None = None
    due_date: date | None = None
    erp_deal_id: int | None = None
    """
    Связь с проектом (заявкой) ERP
    """
    deal_number: Annotated[str | None, Field(max_length=64)] = None


class DocumentArchivedV1(BaseModel):
    """
    Тип uz.railtech.eds.document.archived.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Документ реестра (в том числе входящее письмо) перенесён в архив; номер не освобождается (runbook §2.1).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    document: DocumentRef
    archived_at: AwareDatetime
    reason: Annotated[str | None, Field(max_length=1000)] = None
    actor: Actor


class DocumentKind(StrEnum):
    """
    Тип документа реестра EDS: входящее, исходящее письмо, служебная записка, заявление, отчёт
    """

    letter_in = "letter_in"
    letter_out = "letter_out"
    memo = "memo"
    application = "application"
    report = "report"


class DocumentRef(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    eds_document_id: Uuid
    kind: DocumentKind
    number: RegistryNumber


class DocumentRegisteredV1(BaseModel):
    """
    Тип uz.railtech.eds.document.registered.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Документ получил номер реестра: служебная записка (СЗ), заявление (ЗЯ), отчёт (ОТ) — при создании; исходящее письмо (ИСХ) — при отправке. Входящие письма — letter.registered.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    document: Document
    actor: Actor


class EdsPermission(StrEnum):
    """
    Код права EDS v1 (runbook волны 12 §2.2; platform-rbac.yaml, backend.eds)
    """

    letters_read = "letters.read"
    letters_register = "letters.register"
    letters_resolve = "letters.resolve"
    memos_create = "memos.create"
    memos_approve = "memos.approve"
    approvals_decide = "approvals.decide"
    registry_read = "registry.read"
    registry_export = "registry.export"


class ErpLinks(BaseModel):
    """
    Ссылки на коммерческие объекты ERP и клиента CRM. Ключи erp_request_id, erp_deal_id, deal_number есть всегда; null — письмо ещё не связано с заявкой (зарегистрировано вручную до erp.request.created)
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_request_id: int | None
    """
    Заявка ERP (request.created)
    """
    erp_deal_id: int | None
    """
    Сделка ERP (Deal), к которой относится письмо
    """
    deal_number: Annotated[str | None, Field(max_length=64)]
    """
    Бизнес-номер заявки или проекта ERP (ЗВ-ГГГГ-NNN, ПР-ГГГГ-NNN)
    """
    crm_client_id: int | None = None
    erp_company_id: int | None = None


class Letter(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    eds_letter_id: Uuid
    number: LetterNumber
    subject: Annotated[str, Field(max_length=300, min_length=1)]
    received_at: date
    """
    Дата получения письма
    """
    registered_at: AwareDatetime
    sender: Sender
    """
    Отправитель — организация клиента. Письмо, зарегистрированное автоматически по uz.railtech.erp.request.created.v1, может не знать имени (null): клиент — по links.crm_client_id
    """
    addressee: PersonRef | None = None
    """
    На чьё имя (по умолчанию — директор)
    """
    urgent: bool | None = None


class LetterNumber(RootModel[str]):
    root: Annotated[str, Field(pattern="^ВХ-\\d{3,}/\\d{2}$")]
    """
    Номер входящего ВХ-NNN/ГГ; счётчик — на год по Asia/Tashkent, без пропусков
    """


class LetterRef(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    eds_letter_id: Uuid
    number: LetterNumber
    subject: Annotated[str, Field(max_length=300, min_length=1)]


class LetterRegisteredV1(BaseModel):
    """
    Тип uz.railtech.eds.letter.registered.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Письмо получило номер ВХ-NNN/ГГ в реестре EDS и ждёт резолюции директора: вручную (POST /api/v1/letters) или автоматически по uz.railtech.erp.request.created.v1 (связь с заявкой — links). Подписчики v1: platform-bff.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    letter: Letter
    links: ErpLinks
    actor: Actor


class LetterRejectedV1(BaseModel):
    """
    Тип uz.railtech.eds.letter.rejected.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Директор отклонил письмо с причиной (обязательна). Что делает ERP: сделка links.erp_deal_id → LOST с причиной reason.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    letter: LetterRef
    links: ErpLinks
    reason: Annotated[str, Field(max_length=4000, min_length=1)]
    actor: Actor


class LetterResolvedV1(BaseModel):
    """
    Тип uz.railtech.eds.letter.resolved.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Директор утвердил резолюцию: исполнители (crm_user_id, зона), срок, минимальная маржа, ссылки на заявку и сделку ERP. Что делает ERP (EDS-01): задание расчёта по сделке links.erp_deal_id исполнителям, стадия CALCULATION; links.erp_deal_id = null — пропуск с записью в журнал.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    letter: LetterRef
    links: ErpLinks
    resolution: Resolution
    actor: Actor


class LetterReturnedV1(BaseModel):
    """
    Тип uz.railtech.eds.letter.returned.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Директор вернул письмо менеджеру с комментарием (обязателен). Подписчики v1: platform-bff (подсказка).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    letter: LetterRef
    links: ErpLinks
    comment: Annotated[str, Field(max_length=4000, min_length=1)]
    actor: Actor


class MarginPct(RootModel[str]):
    root: Annotated[str, Field(pattern="^(100(\\.0{1,2})?|\\d{1,2}(\\.\\d{1,2})?)$")]
    """
    Процент маржи 0–100, до двух знаков после точки, строкой (как деньги): «12.5»
    """


class Money(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    amount: Amount
    currency: Currency


class OutgoingNumber(RootModel[str]):
    root: Annotated[str, Field(pattern="^ИСХ-\\d{3,}/\\d{2}$")]
    """
    Исходящий номер ИСХ-NNN/ГГ: при одобрении КП и при отправке письма
    """


class PersonRef(BaseModel):
    """
    Сотрудник: crm_user_id (идентичность — CRM) и имя из проекции EDS на момент события
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_user_id: int
    full_name: Annotated[str, Field(max_length=255, min_length=1)]


class RegistryNumber(RootModel[str]):
    root: Annotated[
        str,
        Field(
            pattern="^(ВХ-\\d{3,}/\\d{2}|ИСХ-\\d{3,}/\\d{2}|(СЗ|ЗЯ|ОТ)-\\d{4}/\\d{3,})$"
        ),
    ]
    """
    Номер документа реестра EDS: ВХ-NNN/ГГ, ИСХ-NNN/ГГ, СЗ-ГГГГ/NNN, ЗЯ-ГГГГ/NNN, ОТ-ГГГГ/NNN
    """


class Resolution(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    text: Annotated[str, Field(max_length=4000, min_length=1)]
    assignees: Annotated[list[Assignee], Field(min_length=1)]
    """
    Исполнители расчёта с зоной ответственности
    """
    due: date
    """
    Срок расчёта
    """
    min_margin_pct: MarginPct | None
    """
    «Маржа не ниже, %»; null — ограничения нет. Порог для чек-листа одобрения КП
    """
    decided_by: PersonRef
    decided_at: AwareDatetime


class RouteStatus(StrEnum):
    """
    Состояние маршрута после решения: open — есть следующий шаг; иначе маршрут закрыт
    """

    open = "open"
    approved = "approved"
    returned = "returned"
    rejected = "rejected"


class SendChannel(StrEnum):
    """
    Канал отправки КП клиенту, выбранный директором при одобрении (SPEC-v3 §7.3)
    """

    telegram = "telegram"
    cabinet = "cabinet"
    email = "email"


class Sender(BaseModel):
    """
    Отправитель — организация клиента. Письмо, зарегистрированное автоматически по uz.railtech.erp.request.created.v1, может не знать имени (null): клиент — по links.crm_client_id
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    name: Annotated[str | None, Field(max_length=255)]
    inn: Annotated[str | None, Field(pattern="^\\d{9,14}$")] = None


class Step(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    index: Annotated[int, Field(ge=1)]
    """
    Номер шага маршрута с 1
    """
    assignee: StepAssignee


class StepAssignee(BaseModel):
    """
    Кто решает на шаге: конкретный сотрудник (crm_user_id) или любой с правом EDS (permission); ровно одно из двух не null
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_user_id: int | None
    permission: EdsPermission | None


class Type(StrEnum):
    system = "system"
    staff = "staff"


class Uuid(RootModel[UUID]):
    root: UUID


class Zone(StrEnum):
    """
    Зона ответственности исполнителя резолюции (SPEC-v3 §7.3): goods — товары, склад, цены поставщиков (раздел erp.calc.goods, снабженец); services — услуги, ТЗ, бригада (erp.calc.services, гл. инженер); payment_terms — условия оплаты (бухгалтер)
    """

    goods = "goods"
    services = "services"
    payment_terms = "payment_terms"

# Сгенерировано scripts/gen_python.py из packages/contracts/events/ — не править руками (make contracts).

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, RootModel


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
    Тип uz.railtech.eds.approval.decided.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Решение на шаге маршрута: approve, return (на доработку), reject; comment обязателен для return и reject. route_status — состояние маршрута после решения (open — есть следующий шаг). Что делает ERP (EDS-03) для approval.object.kind = quote и закрытого маршрута: approved — ИСХ-номер outgoing_number на КП, отправка по channels разблокирована; returned — КП «На доработке» с комментарием; rejected — КП отклонено директором. Одобрение КП, готового позже срока резолюции, допустимо (строка «срок» чек-листа — предупреждение) и помечается approved_late = true.
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
    approved_late: bool | None = None
    """
    Для одобренного КП: true — директор одобрил КП, готовое позже срока резолюции, осознанно приняв опоздание (строка чек-листа due — предупреждение, не блок; решение архитектора 2026-10-26, C1-G-1). Нет поля или false — срок выдержан или не задан. Необязательное
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
    Тип uz.railtech.eds.approval.requested.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Шаг маршрута стал текущим: открыт маршрут (или новый круг после возврата) — первый шаг; решение `approve` передало маршрут дальше — следующий шаг (например, бухгалтер после директора). step.index — номер этого шага, step.assignee — кто решает. Для КП — после uz.railtech.erp.quote.ready_for_approval.v1. Подписчики v1: platform-bff (колокольчик, «Моя очередь»).
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


class Attachment(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
    )
    filename: Annotated[str, Field(max_length=255, min_length=1)]
    content_type: Annotated[
        str, Field(max_length=127, pattern="^[a-z0-9.+-]+/[A-Za-z0-9.+-]+$")
    ]
    size: Annotated[int, Field(ge=0, le=20971520)]
    """
    Байт; не больше 20 МиБ на файл
    """
    sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$")]
    """
    Контрольная сумма содержимого: CRM сверяет скачанное
    """


class Content(BaseModel):
    """
    Тело письма шифртекстом: Fernet с ключом urlsafe_b64(HMAC-SHA256(секрет пары «eds → crm», "rt-mail/v1/content")); открытый текст — JSON {text, html|null, links: [{url, expires_at}]}. Первым шифрует первый секрет пары, CRM пробует каждый действующий
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    alg: Literal["fernet-pair-v1"]
    ciphertext: Annotated[str, Field(max_length=4194304, min_length=1)]


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
    Тип uz.railtech.eds.document.archived.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Документ перенесён в архив; номер не освобождается (runbook §2.1). Публикуется автоматически, без отдельной операции: маршрут документа завершён окончательно — одобрен на последнем шаге (служебная записка без суммы, заявление, отчёт — approved; с суммой — paid) или отклонён (rejected); исходящее письмо — при отправке (sent). Документ сохраняет итоговый статус. Входящие письма (kind = letter_in) в C1 в архив не переносятся.
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


class EdsPermission(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z_]+\\.[a-z_]+$")]
    """
    Код права EDS (runbook волны 12 §2.2). Шаблон, а не перечень: новый код не ломает события v1; перечень кодов — EdsPermission в openapi/eds.yaml и edsPermission в platform-rbac.schema.json
    """


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
    Отправитель — организация клиента. Письмо, зарегистрированное автоматически по uz.railtech.erp.request.created.v1, берёт имя, ИНН и контакт из payload заявки (company_name, company_inn, contact_name); старое событие без них — имя null, клиент — по links.crm_client_id
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


class MailRequestedV1(BaseModel):
    """
    Тип uz.railtech.eds.mail.requested.v1, источник rt://eds. Поле data конверта (envelope.v1.json). Исходящую почту ансамбля отправляет только почтовый сервис CRM (W18A-P1, B-INB-6): EDS письмо сама не шлёт — она рендерит тему, текст и HTML своим шаблоном и публикует это событие в транзакции изменения; CRM доставляет его через SMTP из карточки «Почта» (журнал доставки, повторы, итог). Текст, HTML и ссылки на вложения лежат в content шифртекстом ключа пары «eds → crm» (одноразовые ссылки входа и приглашений не хранятся открыто ни в outbox, ни в inbox). Вложения — по ссылке на объект хранилища отправителя (подписанная ссылка на чтение с ограниченным сроком, ключи S3 у каждого сервиса свои), не байтами в событии. Повтор с тем же request_key второго письма не даёт. Итог доставки CRM публикует событиями uz.railtech.crm.mail.sent.v1 / mail.failed.v1, только если notify = true.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    request_key: Annotated[str, Field(pattern="^[A-Za-z0-9._:/-]{1,128}$")]
    """
    Ключ идемпотентности отправителя: одно письмо на ключ. Повторная публикация с тем же ключом (новый id конверта) второго письма не даёт; итог несёт тот же ключ
    """
    purpose: Annotated[str, Field(pattern="^[a-z][a-z0-9_.-]{0,63}$")]
    """
    Назначение письма — код шаблона отправителя (quote_sent, portal_magic_link, setup_password…): видно в журнале доставки и в итоге
    """
    to: Annotated[list[ToItem], Field(max_length=10, min_length=1)]
    """
    Получатели (одно письмо всем адресам)
    """
    reply_to: Annotated[EmailStr | None, Field(max_length=255)] = None
    """
    Адрес для ответа, если не адрес отправителя карточки «Почта»
    """
    subject: Annotated[str, Field(max_length=255, min_length=1)]
    """
    Тема (без секретов: видна в журнале доставки)
    """
    language: Annotated[str | None, Field(pattern="^[a-z]{2}$")] = None
    """
    Язык письма (ru, uz, en) — для журнала
    """
    ref: Ref | None = None
    """
    Объект отправителя, к которому относится письмо (КП, документ, приглашение) — возвращается в итоге
    """
    notify: bool | None = None
    """
    Нужен ли отправителю итог доставки (uz.railtech.crm.mail.sent.v1 / mail.failed.v1); по умолчанию false
    """
    attachments: Annotated[list[Attachment] | None, Field(max_length=10)] = None
    """
    Метаданные вложений; ссылки на объекты хранилища — в content (links), в том же порядке
    """
    content: Content
    """
    Тело письма шифртекстом: Fernet с ключом urlsafe_b64(HMAC-SHA256(секрет пары «eds → crm», "rt-mail/v1/content")); открытый текст — JSON {text, html|null, links: [{url, expires_at}]}. Первым шифрует первый секрет пары, CRM пробует каждый действующий
    """


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


class Ref(BaseModel):
    """
    Объект отправителя, к которому относится письмо (КП, документ, приглашение) — возвращается в итоге
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    kind: Annotated[str, Field(pattern="^[a-z][a-z0-9_.-]{0,31}$")]
    id: Annotated[str, Field(max_length=64, min_length=1)]


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
    Отправитель — организация клиента. Письмо, зарегистрированное автоматически по uz.railtech.erp.request.created.v1, берёт имя, ИНН и контакт из payload заявки (company_name, company_inn, contact_name); старое событие без них — имя null, клиент — по links.crm_client_id
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    name: Annotated[str | None, Field(max_length=255)]
    inn: Annotated[str | None, Field(pattern="^\\d{9,14}$")] = None
    contact: Annotated[str | None, Field(max_length=255)] = None
    """
    Контактное лицо отправителя (для письма по заявке — из payload.contact_name события erp.request.created). Необязательное, с 2026-10-26 (C1-G-7)
    """


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


class ToItem(RootModel[EmailStr]):
    root: Annotated[EmailStr, Field(max_length=255)]


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

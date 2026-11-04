# Сгенерировано scripts/gen_python.py из packages/contracts/events/ — не править руками (make contracts).

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, RootModel


class Actor(BaseModel):
    """
    Кто изменил: сотрудник CRM, бот или система
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    type: Type
    crm_user_id: int | None = None
    """
    Сотрудник при type=staff
    """


class AiPolicyChangedV1(BaseModel):
    """
    Тип uz.railtech.crm.ai_policy.changed.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Админ сохранил раздел «ИИ» настроек CRM (политика защиты персональных данных перед моделью, решение владельца 2026-11-03): `business` («Деловая», по умолчанию) — в тексте для модели скрываются только паспорт, ПИНФЛ, номера карт и даты рождения; `strict` («Строгая») — ещё и телефоны, почта, ИНН, счета и прочие длинные числа, сканы и фото в модель не уходят. Снимок значения целиком: подписчик заменяет проекцию, снимок с `changed_at` старше или равным применённому не применяется. Событие публикуется и повторно при каждом старте воркера CRM (`changed_at` — время сохранения настройки, нет сохранённой — 1970-01-01). Данных людей и компаний нет.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    pii_policy: PiiPolicy
    """
    Политика маскирования персональных данных перед вызовом модели
    """
    changed_at: AwareDatetime
    """
    Момент сохранения настройки в CRM (время базы)
    """
    actor: Actor


class Author(StrEnum):
    """
    Кто автор сообщения (роль сообщения CRM)
    """

    lead = "lead"
    bot = "bot"
    manager = "manager"
    system = "system"


class Cabinet(BaseModel):
    """
    Чат кабинета (CHAT-1): чьи сообщения ленты кабинета стереть. Стирается только автор: scope=authors — сообщения перечисленных контактов ERP (их пишет человек, обезличенный этим событием; текст удаляется, автор — «Удалённый пользователь»), лента компании, сообщения менеджеров и других контактов остаются; scope=company — стирание клиента целиком: вся лента компании до erased_at, ответы менеджера с sent_at не позже erased_at больше не применяются. Нет поля или null — в ленте кабинета стирать нечего
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    erp_company_id: int
    """
    Компания ERP, чья лента кабинета
    """
    scope: Scope
    erp_contact_ids: list[int]
    """
    Контакты ERP — авторы, чьи сообщения стираются (scope=authors); при scope=company — пусто
    """


class CabinetMessageSentV1(BaseModel):
    """
    Тип uz.railtech.crm.cabinet.message_sent.v1, источник rt://crm (CHAT-1, ADR-0023). Поле data конверта (envelope.v1.json). Менеджер ответил клиенту, последнее входящее сообщение которого пришло из кабинета: CRM пишет сообщение в беседу канала cabinet и это событие одной транзакцией (откат — события нет). Подписчик — ERP: строка ленты кабинета компании erp_company_id, идемпотентно по message_id; поздний ответ с sent_at не позже стирания ленты (crm.lead.erased.v1) не применяется. Текст на шине — по ADR-0023.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    message_id: int
    """
    Сообщение в CRM (ключ идемпотентности у подписчика)
    """
    crm_lead_id: int
    """
    Лид, к которому привязана беседа кабинета (якорь очереди «Сообщения»)
    """
    crm_client_id: int | None
    """
    Клиент CRM беседы; null — компания ещё не сопоставлена клиенту
    """
    erp_company_id: int
    """
    Компания-контрагент в ERP, чья лента получает ответ
    """
    text: Annotated[str, Field(max_length=4000, min_length=1)]
    manager_name: Annotated[str | None, Field(max_length=255)]
    """
    Имя менеджера для подписи в кабинете; null — имени нет
    """
    sent_at: AwareDatetime
    """
    Время записи сообщения в CRM
    """
    actor: Actor


class ChangedField(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z][a-z0-9_]*$")]


class Client(BaseModel):
    """
    Снимок клиента CRM (event-carried state transfer): подписчик заменяет свою проекцию целиком; порядок — по updated_at (более старый снимок не применяется).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_client_id: int
    erp_company_id: int | None
    """
    Компания в ERP, если клиент уже передан; null — ещё нет
    """
    name: Annotated[str, Field(max_length=255, min_length=1)]
    """
    Название клиента (владелец — CRM)
    """
    inn: Annotated[str | None, Field(max_length=32)]
    """
    ИНН (владелец — CRM)
    """
    segment: Annotated[str | None, Field(max_length=64)]
    is_active: bool
    owner: UserRef | None
    """
    Ответственный менеджер
    """
    updated_at: AwareDatetime


class ClientCreatedV1(BaseModel):
    """
    Тип uz.railtech.crm.client.created.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Снимок клиента в client. ERP по нему не создаёт компанию (это делает передача в бэк-офис), а только обновляет проекцию, если erp_company_id известен.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    client: Client
    actor: Actor


class ClientUpdatedV1(BaseModel):
    """
    Тип uz.railtech.crm.client.updated.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Снимок клиента после изменения. Подписчик ERP обновляет проекцию компании (название, ИНН, ответственный) по crm_client_id/erp_company_id; более старый updated_at не применяется.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    client: Client
    changed_fields: list[ChangedField] | None = None
    """
    Необязательно: имена изменённых полей снимка (подсказка; подписчик всё равно применяет снимок целиком)
    """
    actor: Actor


class Contact(BaseModel):
    """
    Снимок контактного лица клиента CRM: подписчик заменяет проекцию целиком; порядок — по updated_at.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_contact_id: int
    crm_client_id: int
    erp_company_id: int | None
    """
    Компания клиента в ERP, если известна
    """
    full_name: Annotated[str, Field(max_length=255, min_length=1)]
    position: Annotated[str | None, Field(max_length=255)]
    phone_e164: Phone | None
    email: Email | None
    telegram_user_id: int | None
    """
    Telegram контакта (вход в Cabinet, доставка кода акцепта ботом CRM); null — Telegram не привязан
    """
    telegram_username: Annotated[str | None, Field(max_length=64)] = None
    """
    Имя пользователя Telegram без @ (NOTIFY-1): кабинет показывает контакту, какой аккаунт привязан; null — нет имени или Telegram не привязан
    """
    telegram_name: Annotated[str | None, Field(max_length=255)] = None
    """
    Имя в профиле Telegram (NOTIFY-1), когда нет имени пользователя; null — неизвестно или Telegram не привязан
    """
    is_primary: bool
    """
    Основной контакт клиента (не более одного)
    """
    language: Language | None = None
    preferred_channel: PreferredChannel | None = None
    updated_at: AwareDatetime


class ContactCreatedV1(BaseModel):
    """
    Тип uz.railtech.crm.contact.created.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Снимок контакта. Подписчик ERP создаёт или обновляет проекцию контакта по crm_contact_id.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    contact: Contact
    actor: Actor


class ContactDeletedV1(BaseModel):
    """
    Тип uz.railtech.crm.contact.deleted.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Подписчик ERP помечает проекцию контакта удалённой (доступ в Cabinet закрывается); повтор — без действий; поздний contact.created/updated с updated_at ≤ deleted_at не применяется.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_contact_id: int
    crm_client_id: int
    erp_company_id: int | None
    """
    Компания клиента в ERP, если известна
    """
    deleted_at: AwareDatetime
    """
    Момент удаления в CRM. Подписчик сравнивает с updated_at снимков contact.*: снимок с updated_at не новее deleted_at после удаления не применяется (поздняя доставка contact.updated не воскрешает контакт)
    """
    actor: Actor


class ContactUpdatedV1(BaseModel):
    """
    Тип uz.railtech.crm.contact.updated.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Снимок контакта после изменения. Подписчик ERP обновляет проекцию по crm_contact_id (нет проекции — создаёт); более старый updated_at не применяется.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    contact: Contact
    changed_fields: list[ChangedField] | None = None
    """
    Необязательно: имена изменённых полей снимка (подсказка; подписчик всё равно применяет снимок целиком)
    """
    actor: Actor


class Direction(StrEnum):
    """
    in — написал лид (клиент); out — ответ бота, менеджера или системное сообщение
    """

    in_ = "in"
    out = "out"


class Email(RootModel[EmailStr]):
    root: Annotated[EmailStr, Field(max_length=255)]


class Language(StrEnum):
    ru = "ru"
    uz = "uz"
    en = "en"


class Lead(BaseModel):
    """
    Снимок лида CRM без контактов и переписки (персональные данные лида не публикуются); порядок — по updated_at.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_lead_id: int
    crm_client_id: int | None
    """
    Клиент, к которому привязан лид; null — ещё нет
    """
    display_name: Annotated[str, Field(max_length=255)]
    company_name: Annotated[str | None, Field(max_length=255)]
    stage: LeadStage
    source: LeadSource
    language: Language
    score: Annotated[int, Field(ge=0, le=100)]
    assigned_user: UserRef | None
    """
    Ответственный
    """
    erp_request_id: int | None
    """
    Заявка ERP, созданная передачей лида; null — не передан
    """
    updated_at: AwareDatetime
    source_detail: Annotated[str | None, Field(pattern="^[a-z][a-z_]{0,15}$")] = None
    """
    Точный источник лида в CRM, если его нет в перечне LeadSource v1 (CHAT-1: cabinet — лид-якорь беседы чата кабинета; в source тогда web — веб-канал). Перечень source расширяется только в lead.*.v2 (ADR-0016)
    """


class LeadCreatedV1(BaseModel):
    """
    Тип uz.railtech.crm.lead.created.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Снимок лида (без контактов и переписки).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    lead: Lead
    actor: Actor


class LeadErasedV1(BaseModel):
    """
    Тип uz.railtech.crm.lead.erased.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Лид обезличен по запросу (/delete, SPEC §6.4). Только идентификаторы и время стирания, никаких данных лида. Подписчики ОБЯЗАНЫ стереть у себя копии персональных данных по этому лиду (имя, компанию, контакты, переписку, производные записи) и не восстанавливать их из более ранних событий; снимки lead.* с updated_at ≤ erased_at после этого не применяются.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_lead_id: int
    crm_client_id: int | None
    """
    Клиент, к которому лид был привязан, если был; null — нет
    """
    erased_at: AwareDatetime
    """
    Момент обезличивания в CRM (время базы)
    """
    actor: Actor
    cabinet: Cabinet | None = None
    """
    Чат кабинета (CHAT-1): чьи сообщения ленты кабинета стереть. Стирается только автор: scope=authors — сообщения перечисленных контактов ERP (их пишет человек, обезличенный этим событием; текст удаляется, автор — «Удалённый пользователь»), лента компании, сообщения менеджеров и других контактов остаются; scope=company — стирание клиента целиком: вся лента компании до erased_at, ответы менеджера с sent_at не позже erased_at больше не применяются. Нет поля или null — в ленте кабинета стирать нечего
    """


class LeadMergedV1(BaseModel):
    """
    Тип uz.railtech.crm.lead.merged.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Два лида с одним телефоном склеены в одну карточку (Telegram-лид и лид с сайта/вручную): lead — снимок выжившего лида после склейки, merged_lead_id — поглощённый лид, которого больше нет. Подписчик удаляет или перепривязывает у себя поглощённый лид к выжившему; повтор — без действий.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    lead: Lead
    merged_lead_id: int
    """
    Поглощённый лид (crm_lead_id), удалён в CRM
    """
    actor: Actor


class LeadMessageAddedV1(BaseModel):
    """
    Тип uz.railtech.crm.lead.message_added.v1, источник rt://crm (D1-1, волна 16). Поле data конверта (envelope.v1.json). Сообщение записано в переписку лида (входящее от лида или исходящее от бота и менеджера) — в той же транзакции, что и строка сообщения. Это сигнал «перезапросите переписку», а не копия: текста, вложений и контактов в событии НЕТ — подписчик читает переписку API CRM с правами сотрудника. Подписчик сегодня один — BFF Платформы (подсказка SSE «messages»); ERP и EDS его не получают. Диалоги песочницы (тест бота) не публикуются. Заметки команды — не сообщения переписки и этим типом не публикуются.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_lead_id: int
    crm_client_id: int | None
    """
    Клиент, к которому привязан лид; null — ещё не клиент
    """
    message_id: int
    """
    Идентификатор сообщения в CRM (растёт со временем): подписчик может не перезапрашивать уже показанное
    """
    direction: Direction
    """
    in — написал лид (клиент); out — ответ бота, менеджера или системное сообщение
    """
    author: Author
    """
    Кто автор сообщения (роль сообщения CRM)
    """
    channel: Annotated[str, Field(pattern="^[a-z][a-z_]{0,15}$")]
    """
    Канал переписки (telegram, …) — из диалога CRM
    """
    has_attachments: bool
    """
    У сообщения есть вложения (сами файлы — только через API CRM)
    """
    handoff: bool
    """
    Лид ждёт человека или уже у менеджера (owner_mode не bot): сообщение важно для «Ждут ответа» и счётчиков
    """
    crm_assigned_user_id: int | None
    """
    Ответственный менеджер лида на момент сообщения; null — нет (адресная доставка подсказок — хвост)
    """
    sent_at: AwareDatetime
    """
    Время записи сообщения в CRM
    """
    actor: Actor


class LeadSource(StrEnum):
    telegram = "telegram"
    web = "web"
    phone = "phone"
    email = "email"
    referral = "referral"
    sandbox = "sandbox"


class LeadStage(StrEnum):
    new = "new"
    engaged = "engaged"
    qualified = "qualified"
    handoff = "handoff"
    in_progress = "in_progress"
    won = "won"
    customer = "customer"
    lost = "lost"
    unresponsive = "unresponsive"


class LeadStageChangedV1(BaseModel):
    """
    Тип uz.railtech.crm.lead.stage_changed.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Переход стадии и снимок лида после него.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    lead: Lead
    from_: Annotated[LeadStage, Field(alias="from")]
    to: LeadStage
    reason: Annotated[str | None, Field(max_length=500)] = None
    """
    Код причины из справочника CRM (snake_case, например taken_by_manager, closed_won, qualifier, no_reply); свободный текст сотрудника в событие не попадает и остаётся в CRM
    """
    actor: Actor


class LeadUpdatedV1(BaseModel):
    """
    Тип uz.railtech.crm.lead.updated.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Снимок лида после изменения (кроме смены стадии — для неё lead.stage_changed).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    lead: Lead
    changed_fields: list[ChangedField] | None = None
    """
    Необязательно: что изменилось — имена полей снимка или признак лида вне снимка: `handoff` — бот открыл новую передачу менеджеру (D1-1). Подсказка; подписчик всё равно применяет снимок целиком
    """
    actor: Actor


class MailFailedV1(BaseModel):
    """
    Тип uz.railtech.crm.mail.failed.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Итог запроса uz.railtech.<домен>.mail.requested.v1 с notify = true: письмо окончательно не ушло — постоянная ошибка SMTP (адрес отклонён), исчерпаны повторы временной ошибки, почта не настроена, вложение недоступно или тело не расшифровано. Без текста письма и адресов (W18A-P1).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    requester: Annotated[str, Field(pattern="^[a-z][a-z0-9-]{0,31}$")]
    """
    Кто запросил письмо (erp, eds) — подписчик применяет только свои итоги
    """
    request_key: Annotated[str, Field(pattern="^[A-Za-z0-9._:/-]{1,128}$")]
    """
    Ключ идемпотентности из запроса
    """
    purpose: Annotated[str, Field(pattern="^[a-z][a-z0-9_.-]{0,63}$")]
    ref: Ref | None = None
    """
    Объект отправителя из запроса
    """
    email_log_id: int
    """
    Строка журнала доставки CRM
    """
    attempts: Annotated[int | None, Field(ge=0)] = None
    """
    Попыток SMTP
    """
    failed_at: AwareDatetime
    reason: Annotated[str, Field(pattern="^[a-z][a-z0-9_]{0,63}$")]
    """
    Код причины: smtp_not_configured, rejected, auth_failed, unavailable, tls_failed, invalid_host, attachment_unavailable, content_unreadable… (список открытый — новый код не ломает подписчика)
    """
    detail: Annotated[str | None, Field(max_length=500)] = None
    """
    Пояснение для журнала (код ответа SMTP), без секретов
    """


class MailSentV1(BaseModel):
    """
    Тип uz.railtech.crm.mail.sent.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Итог запроса uz.railtech.<домен>.mail.requested.v1 с notify = true: SMTP-релей карточки «Почта» принял письмо. Без текста письма и адресов — только ключ запроса, назначение и объект отправителя (W18A-P1).
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    requester: Annotated[str, Field(pattern="^[a-z][a-z0-9-]{0,31}$")]
    """
    Кто запросил письмо (erp, eds) — подписчик применяет только свои итоги
    """
    request_key: Annotated[str, Field(pattern="^[A-Za-z0-9._:/-]{1,128}$")]
    """
    Ключ идемпотентности из запроса
    """
    purpose: Annotated[str, Field(pattern="^[a-z][a-z0-9_.-]{0,63}$")]
    ref: Ref | None = None
    """
    Объект отправителя из запроса
    """
    email_log_id: int
    """
    Строка журнала доставки CRM
    """
    attempts: Annotated[int | None, Field(ge=0)] = None
    """
    Попыток SMTP
    """
    sent_at: AwareDatetime
    """
    Когда SMTP-релей принял письмо
    """


class Phone(RootModel[str]):
    root: Annotated[str, Field(pattern="^\\+[1-9][0-9]{6,14}$")]
    """
    Телефон в E.164
    """


class PiiPolicy(StrEnum):
    """
    Политика маскирования персональных данных перед вызовом модели
    """

    business = "business"
    strict = "strict"


class PreferredChannel(StrEnum):
    telegram = "telegram"
    email = "email"
    both = "both"


class Ref(BaseModel):
    """
    Объект отправителя из запроса
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    kind: Annotated[str, Field(pattern="^[a-z][a-z0-9_.-]{0,31}$")]
    id: Annotated[str, Field(max_length=64, min_length=1)]


class Scope(StrEnum):
    authors = "authors"
    company = "company"


class Type(StrEnum):
    system = "system"
    staff = "staff"
    bot = "bot"


class UserRef(BaseModel):
    """
    Сотрудник CRM (ответственный)
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_user_id: int
    full_name: Annotated[str, Field(max_length=255)]

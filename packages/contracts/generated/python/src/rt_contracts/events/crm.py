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
    Необязательно: имена изменённых полей снимка (подсказка; подписчик всё равно применяет снимок целиком)
    """
    actor: Actor


class Phone(RootModel[str]):
    root: Annotated[str, Field(pattern="^\\+[1-9][0-9]{6,14}$")]
    """
    Телефон в E.164
    """


class PreferredChannel(StrEnum):
    telegram = "telegram"
    email = "email"
    both = "both"


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

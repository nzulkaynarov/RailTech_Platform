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


class EdsPermission(RootModel[str]):
    root: Annotated[str, Field(pattern="^[a-z_]+\\.[a-z_]+$")]
    """
    Код права EDS (docs/runbooks/wave12-eds-c1.md §2.2). Шаблон, а не перечень: новый код EDS не ломает identity v1; перечень кодов — EdsPermission в openapi/eds.yaml и edsPermission в platform-rbac.schema.json
    """


class Email(RootModel[EmailStr]):
    root: Annotated[EmailStr, Field(max_length=255)]


class ErpRoleCode(StrEnum):
    """
    Системная роль бэк-офиса ERP (SystemRoleCode в openapi/erp-integration.yaml)
    """

    CALCULATION = "CALCULATION"
    CATALOG_SUPPLY = "CATALOG_SUPPLY"
    FULFILLMENT = "FULFILLMENT"
    FINANCE = "FINANCE"
    HEAD = "HEAD"
    VIEWER = "VIEWER"


class Language(StrEnum):
    ru = "ru"
    uz = "uz"
    en = "en"


class Permissions(BaseModel):
    """
    Необязательно (v1, аддитивно с волны 12): права сотрудника в сервисах, которые сами ролей не ведут; CRM вычисляет их из ролей Платформы по каталогу platform-rbac.yaml (backend.<сервис>). eds — коды прав EDS. Нет поля permissions, нет permissions.eds или пустой список — доступа к EDS нет (CRM до задачи E4 публикует снимок без поля). Подписчик заменяет права целиком по снимку
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    eds: list[EdsPermission] | None = None
    sections: dict[str, Sections] | None = None
    """
    Необязательно (v1, аддитивно с D1-8): разделы каталога platform-rbac.yaml модулей EDS и ERP (ключи `eds.*`, `erp.*`), которые даёт сотруднику объединение матриц его ролей, и уровень (full ⊇ read); скрытых разделов нет, разделы CRM, чатов и настроек не публикуются. Нужны сервисам, которые проверяют не код права, а раздел (EDS: зона исполнителя резолюции — erp.calc.goods, erp.calc.services, eds.payments). У неактивного сотрудника — пусто. Нет поля — разделы неизвестны (снимок до D1-8), подписчик считает, что их нет. Подписчик заменяет разделы целиком по снимку
    """


class PlatformRoleCode(RootModel[str]):
    root: Annotated[str, Field(pattern="^[A-Z][A-Z0-9_]*$")]
    """
    Код роли Платформы из platform-rbac.yaml (MANAGER, DIRECTOR, SUPPLY, ENGINEER, ACCOUNTANT, ADMIN, …)
    """


class Sections(StrEnum):
    full = "full"
    read = "read"


class System(StrEnum):
    crm = "crm"
    erp = "erp"


class Type(StrEnum):
    system = "system"
    staff = "staff"
    bot = "bot"


class User(BaseModel):
    """
    Снимок сотрудника (идентичность v1 живёт в CRM, ADR-0015): без пароля, токенов, Telegram и журнала входов; порядок — по updated_at.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_user_id: int
    email: Email
    """
    Рабочая почта — логин
    """
    full_name: Annotated[str, Field(max_length=255, min_length=1)]
    position: Annotated[str | None, Field(max_length=120)]
    language: Language
    is_active: bool
    platform_roles: list[PlatformRoleCode]
    """
    Роли Платформы; пусто — роли ведутся вручную
    """
    systems: list[System]
    """
    Куда сотруднику можно (platform_access в CRM)
    """
    erp_role_codes: list[ErpRoleCode] | None = None
    """
    Системные роли ERP (как role_codes провижининга)
    """
    permissions: Permissions | None = None
    """
    Необязательно (v1, аддитивно с волны 12): права сотрудника в сервисах, которые сами ролей не ведут; CRM вычисляет их из ролей Платформы по каталогу platform-rbac.yaml (backend.<сервис>). eds — коды прав EDS. Нет поля permissions, нет permissions.eds или пустой список — доступа к EDS нет (CRM до задачи E4 публикует снимок без поля). Подписчик заменяет права целиком по снимку
    """
    updated_at: AwareDatetime


class UserCreatedV1(BaseModel):
    """
    Тип uz.railtech.identity.user.created.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Идентичность v1 живёт в CRM (ADR-0015). Снимок сотрудника в user; секретов нет.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    user: User
    actor: Actor


class UserDeactivatedV1(BaseModel):
    """
    Тип uz.railtech.identity.user.deactivated.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Подписчик закрывает доступ и сессии сотрудника; повтор — без действий.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    crm_user_id: int
    reason: Annotated[str | None, Field(max_length=500)] = None
    actor: Actor


class UserUpdatedV1(BaseModel):
    """
    Тип uz.railtech.identity.user.updated.v1, источник rt://crm. Поле data конверта (envelope.v1.json). Снимок сотрудника после изменения (роли, доступ, имя, должность, язык); более старый updated_at не применяется.
    """

    model_config = ConfigDict(
        extra="ignore",
    )
    user: User
    changed_fields: list[ChangedField] | None = None
    """
    Необязательно: имена изменённых полей снимка (подсказка; подписчик всё равно применяет снимок целиком)
    """
    actor: Actor

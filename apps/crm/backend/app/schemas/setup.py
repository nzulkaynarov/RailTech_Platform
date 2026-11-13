"""DTO мастера первого запуска, чек-листа настройки и бэкапов (scope-аудит §3 п. 7, 9; §4)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ChecklistKey = Literal[
    "company",
    "business_hours",
    "models",
    "bot",
    "channel",
    "kb",
    "team",
    "test_dialog",
    "erp",
    "mail",
    "first_employee",
]


class SetupState(BaseModel):
    needs_setup: bool
    # Название компании из настроек (`company.name`; задача «Н3»): заголовок и экран входа
    # Платформы — до входа, поэтому в публичном ответе. Не секрет: его видит любой на входе.
    company_name: str = ""


class SetupAdminRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class ChecklistItem(BaseModel):
    key: ChecklistKey
    done: bool
    link: str
    unchecked: bool = Field(
        default=False,
        description="Проверка не выполнялась: шаг не «Готово» и не «Не сделано» — «Не проверено»",
    )


class SetupChecklist(BaseModel):
    items: list[ChecklistItem]
    done: int
    total: int


CabinetUrlSource = Literal["saved", "env", "none"]
CabinetCheckResult = Literal["ok", "not_set", "unreachable", "bad_status", "not_cabinet"]


class CabinetUrlOut(BaseModel):
    """Адрес кабинета клиента (D17G-3): действующий адрес и откуда он взят."""

    url: str | None = Field(
        description="Действующий адрес; null — не задан ни в настройках, ни в окружении"
    )
    source: CabinetUrlSource = Field(
        description=(
            "`saved` — задан администратором, `env` — из окружения сервера (CABINET_DOMAIN), "
            "`none` — нет"
        )
    )
    env_url: str | None = Field(description="Адрес из окружения сервера (значение по умолчанию)")


class CabinetUrlIn(BaseModel):
    url: str = Field(
        max_length=500,
        description="Адрес кабинета https://…; пустая строка — вернуть адрес из окружения",
    )


class CabinetCheckIn(BaseModel):
    url: str | None = Field(
        default=None,
        max_length=500,
        description="Проверить этот адрес (ещё не сохранённый); нет — действующий",
    )


class CabinetCheckOut(BaseModel):
    """Итог `GET <адрес>/health` с сервера CRM: кабинет отвечает `200 healthy`."""

    result: CabinetCheckResult
    url: str | None
    status_code: int | None = None


class BackupItem(BaseModel):
    name: str
    at: datetime
    size_bytes: int


class BackupDatabase(BaseModel):
    name: str
    last_success_at: datetime | None = Field(description="Последняя копия базы; нет — None")


class BackupsOut(BaseModel):
    available: bool = Field(description="Том бэкапов смонтирован в api / бакет `backups` читается")
    source: Literal["volume", "rustfs"] = Field(
        description="Откуда статус: том backup-контейнера (dev) или бакет `backups` RustFS (прод)"
    )
    can_request: bool = Field(description="«Сделать сейчас» доступно (только для тома)")
    error: Literal["bucket_missing", "access_denied", "unreachable"] | None = Field(
        description="Почему бакет не прочитан; None — прочитан"
    )
    databases: list[BackupDatabase] = Field(description="Последняя копия по каждой базе (бакет)")
    last_success_at: datetime | None
    stale: bool = Field(description="Последний успешный бэкап старше 26 ч или его нет")
    requested_at: datetime | None = Field(description="«Сделать сейчас» ждёт сервис бэкапа")
    daemon_alive: bool = Field(description="Сервис бэкапа отвечает: heartbeat свежее 2 мин")
    request_stuck: bool = Field(
        description="Запрос «Сделать сейчас» старше 2 мин без новой копии — можно повторить"
    )
    items: list[BackupItem]

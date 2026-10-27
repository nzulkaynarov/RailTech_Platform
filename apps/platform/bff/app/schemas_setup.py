"""Модели первого запуска и выдачи временного пароля — схемы `Setup*` и `EmployeeCredentials` из
packages/contracts/openapi/platform-bff.yaml (0.10.0, W13-A4)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.schemas_admin import Employee

SetupStepKey = Literal["bot", "erp", "mail", "models", "first_employee"]
SetupStepState = Literal["done", "todo", "unknown"]

# Порядок шагов — как в SPEC-v3 §7.6 и в контракте.
STEP_KEYS: tuple[SetupStepKey, ...] = ("bot", "erp", "mail", "models", "first_employee")

_EMAIL = r"^[^@\s]+@[^@\s]+$"


class SetupState(BaseModel):
    needs_admin: bool


class SetupAdminIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Код и пароль — секреты: не попадают в repr, журнал и сообщения об ошибках валидации.
    code: SecretStr = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=254, pattern=_EMAIL)
    password: SecretStr = Field(min_length=1, max_length=256)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, name: str) -> str:
        if not name.strip():
            raise ValueError("имя не может быть пустым")
        return name.strip()


class SetupStep(BaseModel):
    key: SetupStepKey
    state: SetupStepState


class SetupCompanyStatus(BaseModel):
    required: bool
    can_setup: bool


class SetupChecklist(BaseModel):
    steps: list[SetupStep]
    done: int = Field(ge=0)
    total: int = Field(ge=5, le=5)
    company: SetupCompanyStatus | None


class SetupCompanyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255)
    inn: str | None = Field(default=None, max_length=20)
    legal_address: str | None = None
    phone: str | None = Field(default=None, max_length=50)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, name: str) -> str:
        if not name.strip():
            raise ValueError("название не может быть пустым")
        return name.strip()


class SetupCompanyCreated(BaseModel):
    id: int
    name: str


class EmployeeCredentials(BaseModel):
    """Сотрудник и его временный пароль: показывается один раз, в журнал и кэш не попадает."""

    employee: Employee
    temporary_password: str = Field(min_length=1)

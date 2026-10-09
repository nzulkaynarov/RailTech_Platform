"""DTO аутентификации, профиля и пользователей (SPEC §10.1)."""

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["admin", "manager", "viewer"]
UiMode = Literal["admin", "manager"]


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 — тип токена, не секрет
    expires_in: int
    must_change_password: bool


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str
    roles: list[str]
    is_active: bool
    tg_user_id: int | None
    must_change_password: bool
    ui_mode: str


class MePatch(BaseModel):
    ui_mode: UiMode


class PermissionsResponse(BaseModel):
    roles: list[str]
    permissions: dict[str, dict[str, bool]]


class UserCreate(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    roles: list[Role] = Field(min_length=1)


class UserCreated(BaseModel):
    user: UserOut
    temporary_password: str = Field(description="Показывается один раз")


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    roles: list[Role] | None = Field(default=None, min_length=1)
    is_active: bool | None = None
    tg_user_id: int | None = Field(default=None, gt=0)
    clear_tg_user_id: bool = False
    # При деактивации: кому передать лидов, которых ведёт пользователь (ADR-0015).
    transfer_to_user_id: int | None = Field(default=None, gt=0)


class PasswordReset(BaseModel):
    temporary_password: str

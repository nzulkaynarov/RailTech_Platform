"""Профиль сотрудника для страницы /me (W15-H6) — схемы `Profile`, `ProfileUpdate`, `TelegramLink`,
`DeputyUpdate`, `Colleague`, `ForgotPasswordIn`, `ResetPasswordIn` из platform-bff.yaml (0.18.0).

Данные приносит CRM (`GET /api/v1/me`, ADR-0015); BFF переводит поля и прячет числовой id Telegram.
"""

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.session import Language

UserId = Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]
_EMAIL = r"^[^@\s]+@[^@\s]+$"


class TelegramState(BaseModel):
    linked: bool
    username: str | None = None


class DeputyPeriod(BaseModel):
    user_id: UserId
    name: str
    date_from: str
    date_to: str


class Covering(DeputyPeriod):
    """За кого сотрудник сегодня заместитель (та же форма, что и назначенный заместитель)."""


class Profile(BaseModel):
    name: str
    email: str
    position: str | None = None
    phone: str | None = None
    language: Language
    timezone: str
    email_signature: str | None = None
    avatar_url: str | None = None
    telegram: TelegramState
    deputy: DeputyPeriod | None = None
    covering: list[Covering]


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=40)
    language: Language | None = None
    timezone: str | None = Field(default=None, max_length=64)
    email_signature: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _not_empty(self) -> "ProfileUpdate":
        if not self.model_fields_set:
            raise ValueError("укажите хотя бы одно поле")
        if any(getattr(self, name) is None for name in self.model_fields_set):
            raise ValueError("поле не может быть null")
        return self

    def to_crm(self) -> dict[str, Any]:
        """Тело `PATCH /api/v1/me` CRM: имя там `full_name`."""
        payload = {name: getattr(self, name) for name in self.model_fields_set}
        if "name" in payload:
            payload["full_name"] = payload.pop("name")
        return payload


class TelegramLink(BaseModel):
    url: str
    expires_at: str


class Colleague(BaseModel):
    id: UserId
    name: str
    position: str | None = None


class DeputyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deputy_id: UserId
    date_from: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    date_to: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class ForgotPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=254)


class ForgotPasswordAccepted(BaseModel):
    accepted: bool = True


class ResetPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=20, max_length=128)
    new_password: str = Field(min_length=8, max_length=256)


def avatar_url(user_id: int | str, version: int | None) -> str | None:
    """Адрес фото на BFF; версия в адресе меняет кэш браузера при замене."""
    return f"/api/v1/staff/{user_id}/avatar?v={version}" if version else None


def to_profile(crm: dict[str, Any], covering: list[dict[str, Any]]) -> Profile:
    """Профиль из `MeOut` CRM и списка `CoveredOut`."""
    deputy = None
    if crm.get("deputy_user_id") and crm.get("deputy_from") and crm.get("deputy_to"):
        deputy = DeputyPeriod(
            user_id=str(crm["deputy_user_id"]),
            name=str(crm.get("deputy_name") or ""),
            date_from=str(crm["deputy_from"]),
            date_to=str(crm["deputy_to"]),
        )
    return Profile(
        name=str(crm["full_name"]),
        email=str(crm["email"]),
        position=crm.get("position") or None,
        phone=crm.get("phone") or None,
        language=crm.get("language") or "ru",
        timezone=str(crm.get("timezone") or "Asia/Tashkent"),
        email_signature=crm.get("email_signature") or None,
        avatar_url=avatar_url(crm["id"], crm.get("avatar_version")),
        telegram=TelegramState(
            linked=crm.get("tg_user_id") is not None, username=crm.get("tg_username") or None
        ),
        deputy=deputy,
        covering=[
            Covering(
                user_id=str(c["user_id"]),
                name=str(c["full_name"]),
                date_from=str(c["date_from"]),
                date_to=str(c["date_to"]),
            )
            for c in covering
        ],
    )

"""«Партнёр» из карточки лида (ЛП-1): тело и ответ действия."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class PartnerHandoffIn(BaseModel):
    """Форма «Партнёр»: компания, страна, ИНН, контакт и что предлагает кандидат.

    Почта не обязательна (ПК-1): хватает телефона или Telegram лида, приглашение в Кабинет
    уйдёт позже; если почта указана — формат проверяет сервис (`invalid_email`)."""

    company_name: str = Field(min_length=1, max_length=255)
    country: str = Field(default="UZ", min_length=2, max_length=2)
    inn: str = Field(default="", max_length=32)
    kind: Literal["manufacturer", "supplier", "principal", "other"] = "supplier"
    offer: str = Field(min_length=1, max_length=4000)
    contact_name: str = Field(min_length=1, max_length=255)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=32)

    @field_validator("country")
    @classmethod
    def _upper(cls, value: str) -> str:
        return value.strip().upper()


class PartnerHandoffOut(BaseModel):
    """`created = false` — лид уже был передан как партнёр: возвращена первая заявка, второй не
    заведено."""

    lead_id: int
    application_id: int
    created: bool = True

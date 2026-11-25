"""«Партнёр» из карточки лида (ЛП-1): тело и ответ действия."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class PartnerHandoffIn(BaseModel):
    """Форма «Партнёр»: компания, страна, ИНН, контакт и что предлагает кандидат. Нужен хотя бы
    один канал — e-mail
    или телефон."""

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

    @model_validator(mode="after")
    def _channel(self) -> "PartnerHandoffIn":
        if not (self.email.strip() or self.phone.strip()):
            raise ValueError("e-mail or phone is required")
        if self.email.strip() and ("@" not in self.email or " " in self.email.strip()):
            raise ValueError("e-mail is not valid")
        return self


class PartnerHandoffOut(BaseModel):
    """`created = false` — лид уже был передан как партнёр: возвращена первая заявка, второй не
    заведено."""

    lead_id: int
    application_id: int
    created: bool = True

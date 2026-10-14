"""DTO новых источников лидов (M3-CRM-05, ARCHITECTURE §17): форма с сайта и ручное создание."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.settings_base import Language

ManualSource = Literal["phone", "email", "referral"]


class WebFormToken(BaseModel):
    """Токен формы «Запрос»: выдаётся вместе с формой, отправляется в `form_token`."""

    token: str
    expires_at: datetime
    # Форму, отправленную раньше, сервер отклонит (`form_too_fast`).
    min_fill_seconds: int


class WebLeadIn(BaseModel):
    """Форма «Запрос» со страницы входа Cabinet: вложений в первой версии нет (Q-12).

    `consent` — согласие на обработку персональных данных, обязательно `true` (Q-12): иначе
    422 `consent_required`. `website` — honeypot: человек поле не видит; заполнено — запрос
    принят, лид не создан.
    """

    name: str = Field(min_length=1, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    # Хотя бы один контакт: телефон (любой формат с кодом страны или 9 цифр Узбекистана) или e-mail.
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    text: str = Field(min_length=1, max_length=10000)
    language: Language = "ru"
    form_token: str = Field(min_length=1, max_length=64)
    # Не `Literal[True]`: отсутствие и `false` дают один понятный подкод `consent_required`,
    # а не общую ошибку валидации тела.
    consent: bool = Field(
        default=False,
        description="Согласие на обработку персональных данных; обязательно true "
        "(иначе 422 consent_required).",
    )
    website: str | None = Field(default=None, max_length=255)


class WebLeadAccepted(BaseModel):
    """202: запрос принят. `lead_id` пустой — запрос отброшен антиспамом (honeypot)."""

    lead_id: int | None


class ManualLeadIn(BaseModel):
    """«Новый лид» во «Входящих»: звонок, письмо, рекомендация; создавший — ответственный."""

    source: ManualSource
    name: str = Field(min_length=1, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    need: str | None = Field(default=None, max_length=4000)
    language: Language = "ru"

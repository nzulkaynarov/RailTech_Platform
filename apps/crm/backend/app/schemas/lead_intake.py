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


class WebLeadUtm(BaseModel):
    """UTM parameters of the landing URL, as the site saw them; all optional."""

    utm_source: str | None = Field(default=None, max_length=256)
    utm_medium: str | None = Field(default=None, max_length=256)
    utm_campaign: str | None = Field(default=None, max_length=256)
    utm_content: str | None = Field(default=None, max_length=256)
    utm_term: str | None = Field(default=None, max_length=256)


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
    # Origin facts (LID-5), all optional: which form, the landing page path, the referrer, UTM and
    # the language of the landing page. Stored as facts on the lead and shown in its card.
    form: str | None = Field(
        default=None,
        max_length=128,
        description="Form key, e.g. `request`, `site`, `site-customer`, `site-partner`.",
    )
    page: str | None = Field(default=None, max_length=1024, description="Landing page path.")
    referrer: str | None = Field(default=None, max_length=1024)
    utm: WebLeadUtm | None = None
    landing_language: str | None = Field(default=None, max_length=8)


class WebLeadAccepted(BaseModel):
    """202: запрос принят. `lead_id` пустой — запрос отброшен антиспамом (honeypot).

    For the «What next» screen (LID-5): `request_number` is the number to show to the submitter
    (`L-0042`, same as in the staff card) and `first_response_minutes` is the first-response time
    from the «Website forms» settings. Both are null when the request was dropped.
    """

    lead_id: int | None
    request_number: str | None = None
    first_response_minutes: int | None = None


class ManualLeadIn(BaseModel):
    """«Новый лид» во «Входящих»: звонок, письмо, рекомендация; создавший — ответственный."""

    source: ManualSource
    name: str = Field(min_length=1, max_length=255)
    company: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    need: str | None = Field(default=None, max_length=4000)
    language: Language = "ru"

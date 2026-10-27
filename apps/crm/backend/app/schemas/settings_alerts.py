"""Ключ `service_alerts`: оповещения центра внешних сервисов (M3-CRM-12, ADR-0024).

Вынесен из `settings.py`, чтобы тот оставался в лимите размера файла.
"""

from typing import Literal

from pydantic import Field, field_validator

from app.domain.smtp import email_problem
from app.schemas.settings_base import StrictModel


class ServiceAlertsSettings(StrictModel):
    """Кому оповещения центра внешних сервисов о сбое и восстановлении (M3-CRM-12, ADR-0024).

    Одно оповещение о сбое на инцидент и одно о восстановлении; повтор по сервису — не чаще
    `repeat_minutes`. Сбой Telegram оповещается почтой, сбой почты — в Telegram.
    """

    telegram_admins: bool = Field(
        default=True,
        description="Личные сообщения админам с подпиской на системные уведомления",
    )
    # `fallback` — как у монитора (ADR-0018): в канал, только если в личку никому не доставлено.
    telegram_channel: Literal["fallback", "always", "never"] = Field(
        default="fallback", description="Пост в канал команды"
    )
    email_admins: bool = Field(default=True, description="Письмо активным админам с e-mail")
    extra_emails: list[str] = Field(
        default_factory=list, max_length=10, description="Дополнительные адреса для писем"
    )
    repeat_minutes: int = Field(
        default=60,
        ge=15,
        le=1440,
        description=(
            "Устарело и не используется: «Сломано» приходит одно после 15 минут непрерывного "
            "сбоя, не больше одного в сутки на причину (ADR-0024, W15-H3)"
        ),
    )

    @field_validator("extra_emails")
    @classmethod
    def _emails(cls, value: list[str]) -> list[str]:
        cleaned = [v.strip().lower() for v in value if v.strip()]
        bad = [v for v in cleaned if email_problem(v) is not None]
        if bad:
            raise ValueError(f"invalid email: {bad[0]}")
        return list(dict.fromkeys(cleaned))

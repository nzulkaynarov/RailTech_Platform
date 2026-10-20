"""Согласие на обработку данных (SPEC §6.4)."""

from datetime import datetime
from typing import Final, Literal


def consent_required(
    consent_given_at: datetime | None, consent_version: str | None, current_version: str
) -> bool:
    """Нужно (повторно) запросить согласие: не давалось или версия текста сменилась."""
    return consent_given_at is None or consent_version != current_version


# Согласие, которое отмечает сотрудник за лида, заведённого вручную (звонок, письмо, рекомендация):
# лид не пишет боту и подтвердить текст согласия сам не может (D-8; «правовое основание обработки»
# отмечает сотрудник, действие остаётся в аудите — как в HubSpot и Salesforce).
ConsentMethod = Literal["phone", "email", "paper"]
CONSENT_METHODS: Final[tuple[str, ...]] = ("phone", "email", "paper")
# Версия — не текст бота (`settings.texts.consent_version`): бот при первом сообщении лида
# всё равно спросит своё согласие, как и после формы «Запрос» (`lead_intake.WEB_CONSENT_VERSION`).
MANUAL_CONSENT_VERSION: Final = "manual"

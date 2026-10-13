"""Номер перед передачей менеджеру по просьбе лида (решение владельца 2026-10-12). Чистая функция.

Лид сам просит менеджера (кнопка меню, /human, слова «позовите менеджера», «Да» на предложение)
— без подтверждённого Telegram номера передачу не создаём: сначала «Поделиться номером»
(менеджер сможет связаться, защита от спама). Передачи по сигналам бота (стоп-слова, негатив,
цена, квалификатор, вложения, сбой ИИ) не задерживаются никогда. Решает код (CLAUDE.md §1.3).
"""

from typing import Literal

from app.domain.stages import OwnerMode

TriggerSource = Literal["lead", "system"]


def needs_phone_first(
    *,
    required: bool,
    source: TriggerSource,
    has_phone: bool,
    is_client: bool,
    owner_mode: str | None,
    consent_given: bool,
) -> bool:
    """True — не передавать, а сначала попросить номер.

    Только для лида, которого ведёт бот: на паузе (ждёт менеджера) и у менеджера — без изменений;
    до согласия номер не просим — сначала согласие, как и для любого сообщения.
    """
    if not required or source != "lead" or has_phone or is_client or not consent_given:
        return False
    return owner_mode == OwnerMode.BOT

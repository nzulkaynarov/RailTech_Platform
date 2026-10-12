"""Номер перед передачей по просьбе лида (решение владельца 2026-10-12).

Решение — `ClientBotService.hold_handoff_for_phone` (домен `handoff_gate`); здесь только
ответ лиду: текст «зачем номер» с одноразовой клавиатурой «Поделиться номером / Не сейчас»,
запись в переписку и состояние `PhoneForm.pending`. Передачу создаёт `on_own_contact`.
"""

from aiogram import Bot
from aiogram.fsm.context import FSMContext

from app.bot import keyboards
from app.bot.forms import PhoneForm
from app.domain.keywords import find_terms
from app.services.client_bot import ClientBotService
from app.services.conversation import ConversationService, Incoming, Outgoing
from app.services.settings import SettingsService


async def ask_phone_first(
    inc: Incoming,
    bot: Bot,
    conversation: ConversationService,
    client_bot: ClientBotService,
    settings: SettingsService,
    state: FSMContext | None,
) -> bool:
    """True — передача отложена до номера, лиду ответили; False — передавать как обычно."""
    language = await client_bot.hold_handoff_for_phone(inc.tg_user_id)
    if language is None:
        return False
    cfg = await settings.get()
    await conversation.record_lead_message(inc)
    text = cfg.texts.phone_before_manager.get(language)
    await conversation.record_bot_replies(inc.tg_user_id, [Outgoing(text, language=language)])
    await bot.send_message(inc.chat_id, text, reply_markup=keyboards.phone_request(cfg, language))
    if state is not None:
        await state.set_state(PhoneForm.pending)
    return True


async def human_words_wait_for_phone(
    inc: Incoming,
    bot: Bot,
    conversation: ConversationService,
    client_bot: ClientBotService,
    settings: SettingsService,
    state: FSMContext | None,
) -> bool:
    """«Позовите менеджера» словами — те же слова, что у агента (`human_request_terms`)."""
    cfg = await settings.get()
    if not find_terms(inc.text, cfg.escalation.human_request_terms):
        return False
    return await ask_phone_first(inc, bot, conversation, client_bot, settings, state)

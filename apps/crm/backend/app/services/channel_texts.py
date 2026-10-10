"""Словарь текстов канала команды (SPEC §9.1) — одно место для карточки, напоминаний и кнопки.

Канал внутренний, только на русском (CLAUDE.md §11). Формулировки — те же, что в CRM
(`frontend/src/i18n/labels.ru.ts`, `i18n/ru/core.ts`); термин для эскалации — «Передача»
(Q-015). Меняешь метку в CRM — поменяй и здесь (`tests/unit/services/test_channel_texts.py`).
"""

from typing import Final

STAGE: Final[dict[str, str]] = {
    "new": "Новый",
    "engaged": "Вовлечён",
    "qualified": "Квалифицирован",
    "handoff": "Передан",
    "in_progress": "В работе",
    "won": "Сделка",
    "customer": "Клиент",
    "lost": "Отказ",
    "unresponsive": "Не отвечает",
}
PRIORITY: Final[dict[str, str]] = {"hot": "Горячий", "warm": "Тёплый", "info": "Инфо"}
PRIORITY_ICON: Final[dict[str, str]] = {"hot": "🔥", "warm": "🟠", "info": "ℹ️"}
REASONS: Final[dict[str, str]] = {
    "human_requested": "Просит человека",
    "callback_requested": "Просит звонок",
    "price_or_contract_asked": "Цена/условия — нет в базе",
    "negative_sentiment": "Негатив",
    "complaint": "Жалоба",
    "kb_gap_streak": "Бот не нашёл ответ",
    "no_progress": "Нет прогресса",
    "competitor_mentioned": "Конкурент",
    "high_score": "Высокая оценка",
    "qualifier_recommend": "Рекомендация квалификатора",
    "document_not_found": "Документ не найден",
    "service_request": "Сервисный запрос",
    "attachment_received": "Прислал файл",
    "agent_unavailable": "Сбой ИИ-ассистента",
    "delivery_failed": "Не удалось отправить файл",
}
TIMELINES: Final[dict[str, str]] = {
    "<1m": "до 1 мес.",
    "<3m": "до 3 мес.",
    "<12m": "до года",
    ">12m": "больше года",
}
ROLES: Final[dict[str, str]] = {
    "decision_maker": "ЛПР",
    "influencer": "влияет на решение",
    "researcher": "изучает",
}

# Карточка
NO_NAME: Final = "без имени"
LEAD_TITLE: Final = "Лид #{lead_id}"
SCORE: Final = "Оценка {score}"
NEED: Final = "Потребность: {text}"
INTEREST: Final = "Интерес: {text}"
TIMELINE: Final = "Срок: {text}"
ROLE: Final = "Роль: {text}"
WHY: Final = "Почему: {text}"
RECOMMENDATION: Final = "Рекомендация: {text}"
LAST_MESSAGE: Final = "Последнее: 👤 «{text}»"
CRM_LINK: Final = "CRM: {url}"
TAKEN_BY: Final = "✅ Забрал: {name} · {at}"
SNOOZED: Final = "💤 Отложено"
CLOSED: Final = "☑️ Закрыто"
RETURNED: Final = "🤖 Возвращён боту"
SLA_OVERDUE: Final = "⏰ <b>Срок реакции просрочен</b>"

# Кнопки
TAKE_BUTTON: Final = "Забрать"
OPEN_BUTTON: Final = "Открыть в CRM"

# Напоминания и сводка
SLA_REMINDER: Final = "⏰ Срок реакции просрочен: лид #{lead_id} ждёт {minutes} мин"
REMINDER: Final = "🔔 Напоминание: лид #{lead_id} ждёт {minutes} мин"
DIGEST_TITLE: Final = "📋 Открытые передачи: {count}"
DIGEST_LINE: Final = "• {icon} #{lead_id} · {priority} · {url}"

# Ответы на кнопку «Забрать» (всплывающее окно у сотрудника)
NOT_LINKED: Final = (
    "Ваш Telegram не привязан к CRM. Ваш ID: {tg_id}. "
    "Попросите администратора указать его в разделе «Пользователи»."
)
NO_RIGHTS: Final = "Недостаточно прав, чтобы забрать лида."
TEMPORARY_CREDENTIALS_HINT: Final = "Сначала войдите в CRM и смените временный пароль."
TAKEN: Final = "Лид ваш. Откройте карточку в CRM."
TAKEN_BY_OTHER: Final = "Лида уже забрал {name}."
TAKE_FAILED: Final = "Не получилось забрать лида. Откройте карточку в CRM."
REJECTED: Final[dict[str, str]] = {
    "conflict": "Лида уже забрал другой менеджер.",
    "forbidden": NO_RIGHTS,
    "invalid_transition": "Из текущей стадии лида забрать нельзя — откройте карточку в CRM.",
    "not_found": "Лид не найден — возможно, клиент удалил переписку.",
}


def times(n: int) -> str:
    """«2 раза», «5 раз», «21 раз» — для «N раз подряд»."""
    tail, tens = n % 10, n % 100
    return f"{n} раза" if tail in (2, 3, 4) and tens not in (12, 13, 14) else f"{n} раз"


def reason(code: str, kb_gap_streak: int) -> str:
    """Причина передачи словами CRM; для порога «не нашёл ответ» — число из настроек."""
    if code == "kb_gap_streak" and kb_gap_streak > 1:
        return f"{REASONS[code]} {times(kb_gap_streak)} подряд"
    return REASONS.get(code, code)


def stage(code: str) -> str:
    return STAGE.get(code, code)

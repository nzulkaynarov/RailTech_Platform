"""Словарь текстов канала команды (SPEC §9.1) — одно место для карточки, напоминаний и кнопки.

Канал внутренний, только на русском (CONVENTIONS.md §11). Формулировки — те же, что в CRM
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
PHONE: Final = "Номер: {phone}"
PHONE_MISSING: Final = "Номер: не указан"
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
SNOOZED_UNTIL: Final = "💤 Отложено до {until}"
SNOOZED_BY: Final = " · {name}"
WAITING: Final = "⏳ ждёт {waited} · с {since}"
MINUTES: Final = "{n} мин"
HOURS: Final = "{h} ч {m} мин"
DAYS: Final = "{d} д {h} ч"
WEEKDAYS: Final = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
CLOSED: Final = "☑️ Закрыто"
RETURNED: Final = "🤖 Возвращён боту"
SLA_OVERDUE: Final = "⏰ <b>Срок реакции просрочен</b>"

# Кнопки
TAKE_BUTTON: Final = "Забрать"
OPEN_BUTTON: Final = "Открыть"

# Напоминания и сводка (HTML: ссылки — только <a href>, сырые адреса не показываются)
SLA_REMINDER: Final = "⏰ Срок реакции просрочен: {lead} ждёт {waited}"
REMINDER: Final = "🔔 Напоминание: {lead} ждёт {waited}"
LEAD_LINK: Final = '<a href="{url}">лид #{lead_id}</a>'
RAISED_HOT: Final = "🔺 Стал горячим — срок реакции отсчитывается заново"
SNOOZE_OVER: Final = "⏰ Снова открыт после «Отложить»"
DIGEST_TITLE: Final = "📋 Открытые передачи: {count}"
DIGEST_LINE: Final = "• {icon} {lead} · {name} · {why} · ждёт {waited}"
DIGEST_MORE: Final = "…и ещё {count}"

# Личные сообщения сотрудникам
HANDOVER_DM: Final = "👤 Вам передан лид #{lead_id} {name} — {link}"
NEW_WEB_LEAD_DM: Final = (
    "🆕 Новый запрос с сайта #{lead_id}: {who} — {need}. Ответить нужно за {minutes} мин — {link}"
)
WEB_LEAD_OVERDUE_DM: Final = (
    "⏰ Запрос с сайта #{lead_id} ({who}) ждёт ответа дольше {minutes} мин — никто не взял. {link}"
)
CRM_OPEN: Final = '<a href="{url}">открыть</a>'

# Итоги дня (в канал; стоимость моделей — только админам в личку)
REPORT_TITLE: Final = "📊 Итоги дня {day}"
REPORT_LEADS: Final = "• новых лидов: {n}"
REPORT_ESCALATIONS: Final = "• передач: {n} (открыто сейчас: {open})"
REPORT_SLA: Final = "• просрочен срок реакции: {n}"
REPORT_TAKE_MEDIAN: Final = "• медиана до «Забрать»: {waited}"
REPORT_TAKEN_BY: Final = "• забрали: {items}"
REPORT_GAPS: Final = "• открытых пробелов базы знаний: {n}"
REPORT_TOP_GAPS: Final = "• чаще всего не нашёл ответ: {items}"
REPORT_COST: Final = "💵 Стоимость моделей за {day}: {cost}"
REPORT_COST_LIMIT: Final = "{spent} из {limit}"
REPORT_DASHBOARD: Final = '<a href="{url}">Открыть дашборд</a>'

# Алерты монитора (личка админам, запасной путь — канал)
ALERT_FIRE: Final = "⚠️ {title}: {detail}"
ALERT_REPEAT: Final = "⚠️ {title}: {detail} (всё ещё)"
ALERT_RESOLVED: Final = "✅ {title}: в норме"
ALERT_HINT: Final = "Что делать: {hint}"
# Задачи воркера человеческими словами: (название, что делать).
TASKS: Final[dict[str, tuple[str, str]]] = {
    "system_monitor": ("Монитор системы", "проверьте доступность Telegram и базы данных"),
    "daily_report": ("Итоги дня", "проверьте, что бот добавлен в канал команды"),
    "sync_escalation_post": (
        "Карточка передачи в канале",
        "проверьте, что бот — администратор канала команды",
    ),
    "escalation_sla_check": ("Проверка срока реакции", "проверьте канал команды и Telegram"),
    "escalation_reminder": ("Напоминание о передаче", "проверьте канал команды и Telegram"),
    "escalation_digest": ("Утренняя сводка передач", "проверьте канал команды и Telegram"),
    "notify_lead_message": ("Личное сообщение менеджеру", "проверьте Telegram менеджера"),
    "lead_handed_over": ("Сообщение о передаче лида", "проверьте Telegram менеджера"),
    "ingest_kb_document": (
        "Загрузка документа в базу знаний",
        "откройте документ в «Базе знаний» и загрузите заново",
    ),
}
TASK_TITLE: Final = "Задача «{name}»"
TASK_DEFAULT_HINT: Final = "откройте «Состояние системы» и журнал воркера"

# Ответы на кнопку «Забрать» (всплывающее окно у сотрудника)
NOT_LINKED: Final = (
    "Ваш Telegram не привязан к CRM. Ваш ID: {tg_id}. "
    "Попросите администратора указать его в разделе «Пользователи»."
)
NO_RIGHTS: Final = "Недостаточно прав, чтобы забрать лида."
TEMPORARY_CREDENTIALS_HINT: Final = "Сначала войдите в CRM и смените временный пароль."
TAKEN: Final = "Лид ваш. Откройте карточку в CRM."
TAKEN_BY_OTHER: Final = "Лида уже забрал {name}."
HELD_BY_OTHER: Final = "Лида ведёт {name}. Передать его можно в CRM («Передать коллеге»)."
STALE_CARD: Final = "Карточка устарела — обновляю. Откройте лида в CRM."
TAKE_FAILED: Final = "Не получилось забрать лида. Откройте карточку в CRM."
CHANNEL_TEST: Final = (
    "✅ Тестовое сообщение RailTech CRM: канал команды подключён, "
    "сюда будут приходить передачи лидов."
)
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


def task(name: str) -> tuple[str, str]:
    """Задача воркера словами: название и «что делать»; неизвестная — по имени."""
    title, hint = TASKS.get(name, (name, TASK_DEFAULT_HINT))
    return TASK_TITLE.format(name=title), hint


def stage(code: str) -> str:
    return STAGE.get(code, code)

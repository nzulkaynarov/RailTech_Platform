"""Что видит строка «Что ждёт вас» сверх заголовка (ГЛ-1): группа срока, вид работы для фильтра,
глагол кнопки и «почему это у вас».

Группа выводится только из срока строки (`due_label`, который считается от реального срока
источника): просрочено, сегодня, «позже» (остальное, и строки без срока). Вид работы и глагол —
таблицы ниже; «почему у вас» строит сам источник из своего факта (подписант по реестру, резолюция от
даты, «за {имя}», мой клиент, шаг маршрута), а если факта нет — здесь нейтральная фраза по виду."""

from app.feeds.models import DueLabel, QueueCategory, QueueGroup, QueueItem, QueueItemKind

_GROUP: dict[DueLabel, QueueGroup] = {
    "overdue": "overdue",
    "today": "today",
    "tomorrow": "later",
    "later": "later",
    "memo": "later",
}

CATEGORY: dict[QueueItemKind, QueueCategory] = {
    "sign_document": "sign",
    "approve_quote": "approve",
    "approve_memo": "approve",
    "resolve_letter": "resolution",
    "instruction": "instruction",
    "instruction_extension": "instruction",
    "acquaint": "instruction",
    "rework_document": "other",
    "pay_memo": "payment",
    "confirm_payment": "payment",
    "issue_invoice": "payment",
    "overdue_invoice": "payment",
    "answer_lead": "lead",
    "take_lead": "lead",
    "triage_lead": "lead",
    "create_request": "lead",
    "service_request": "lead",
    "inbound_mail": "mail",
    "inbound_mail_mine": "mail",
    "register_reply": "mail",
    "supplier_overdue": "supply",
    "send_supplier_order": "supply",
    "partner_date_change": "supply",
    "receive_goods": "supply",
    "partner_application": "supply",
    "order_shortage": "supply",
    "ship_project": "supply",
    "calc_task": "project",
    "issue_contract": "project",
    "attach_scan": "project",
    "issue_act": "project",
    "problem_project": "project",
    "ticket": "other",
    "integration_issue": "other",
}

# Глагол кнопки: «Подписать», а не «Открыть». Строка, которой здесь нет, получает «Открыть».
ACTION: dict[QueueItemKind, str] = {
    "sign_document": "Подписать",
    "approve_quote": "Одобрить",
    "approve_memo": "Согласовать",
    "pay_memo": "Принять к оплате",
    "resolve_letter": "Наложить резолюцию",
    "instruction": "Исполнить",
    "instruction_extension": "Решить",
    "acquaint": "Ознакомлен",
    "rework_document": "Доработать",
    "answer_lead": "Ответить",
    "take_lead": "Взять",
    "triage_lead": "Разобрать",
    "inbound_mail": "Разобрать",
    "inbound_mail_mine": "Довести",
    "ticket": "Ответить",
    "calc_task": "Рассчитать",
    "confirm_payment": "Подтвердить",
    "issue_invoice": "Выставить",
    "issue_contract": "Оформить",
    "attach_scan": "Приложить скан",
    "issue_act": "Выпустить акт",
    "supplier_overdue": "Выяснить",
    "send_supplier_order": "Отправить",
    "partner_date_change": "Решить",
    "receive_goods": "Принять",
    "partner_application": "Рассмотреть",
    "order_shortage": "Заказать",
    "ship_project": "Отгрузить",
}

# Нейтральное «почему у вас», когда источник своего факта не дал (вид работы даёт роль).
DEFAULT_REASON: dict[QueueItemKind, str] = {
    "sign_document": "вы подписант по реестру полномочий",
    "approve_quote": "ваш шаг одобрения КП",
    "approve_memo": "вы согласующий по маршруту",
    "pay_memo": "ваш шаг: принять к оплате",
    "resolve_letter": "входящее без резолюции",
    "instruction": "поручено вам резолюцией",
    "instruction_extension": "вы автор резолюции",
    "acquaint": "вас просят ознакомиться",
    "rework_document": "вам вернули документ",
    "answer_lead": "ваш клиент ждёт ответа",
    "take_lead": "лид без менеджера",
    "triage_lead": "вы первая линия по лидам",
    "inbound_mail": "общий ящик разбираете вы",
    "inbound_mail_mine": "письмо в вашей работе",
    "ticket": "обращение сотрудника — вы администратор",
    "calc_task": "расчёт поручен вам",
    "confirm_payment": "платёжка клиента ждёт подтверждения",
    "issue_invoice": "счёт ждёт выставления",
    "issue_contract": "проект ждёт договор",
    "attach_scan": "договор подписан — нужен скан",
    "issue_act": "счета оплачены — нужен акт",
    "supplier_overdue": "заказ поставщику просрочен",
    "send_supplier_order": "заказ ждёт отправки партнёру",
    "partner_date_change": "партнёр просит перенести заказ",
    "receive_goods": "заказ ждёт приёмки",
    "partner_application": "заявка на партнёрство",
    "order_shortage": "по проекту не заказано всё нужное",
    "ship_project": "товар проекта в резерве",
}


def group_of(label: DueLabel) -> QueueGroup:
    return _GROUP[label]


def finish(item: QueueItem) -> QueueItem:
    """Дописать строке группу, вид работы, глагол и «почему у вас», если источник не задал свои."""
    update: dict[str, object] = {}
    if item.group is None:
        update["group"] = group_of(item.due_label)
    if item.category is None:
        update["category"] = CATEGORY.get(item.kind, "other")
    if item.action_label is None:
        update["action_label"] = ACTION.get(item.kind, "Открыть")
    if item.reason is None:
        update["reason"] = DEFAULT_REASON.get(item.kind, "по вашей роли")
    return item.model_copy(update=update) if update else item

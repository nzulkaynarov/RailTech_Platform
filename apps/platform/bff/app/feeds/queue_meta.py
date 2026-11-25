"""Что видит строка «Что ждёт вас» сверх заголовка (ГЛ-1): группа срока, вид работы для фильтра,
глагол кнопки и «почему это у вас».

Группа выводится только из срока строки (`due_label`, который считается от реального срока
источника): просрочено, сегодня, «позже» (остальное; строка без срока — тоже «позже»). Вид работы
и глагол — таблицы ниже; «почему у вас» строит сам источник из своего факта (подписант по реестру,
резолюция от даты, «за {имя}», мой клиент, шаг маршрута), а если факта нет — здесь нейтральная
фраза по виду."""

from app.feeds.lang import tr
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
ACTION: dict[QueueItemKind, tuple[str, str, str]] = {
    "sign_document": ("Подписать", "Imzolaş", "Sign"),
    "approve_quote": ("Одобрить", "Maqullaş", "Approve"),
    "approve_memo": ("Согласовать", "Kelişiş", "Approve"),
    "pay_memo": ("Принять к оплате", "Tölovga qabul qiliş", "Accept for payment"),
    "resolve_letter": ("Наложить резолюцию", "Rezolyusiya qöyiş", "Add a resolution"),
    "instruction": ("Исполнить", "Bajariş", "Carry out"),
    "instruction_extension": ("Решить", "Hal qiliş", "Decide"),
    "acquaint": ("Ознакомлен", "Tanişdim", "Acknowledged"),
    "rework_document": ("Доработать", "Qayta işlaş", "Rework"),
    "answer_lead": ("Ответить", "Javob beriş", "Reply"),
    "take_lead": ("Взять", "Oliş", "Take"),
    "triage_lead": ("Разобрать", "Saralaş", "Sort"),
    "inbound_mail": ("Разобрать", "Saralaş", "Sort"),
    "inbound_mail_mine": ("Довести", "Yakunlaş", "Finish"),
    "ticket": ("Ответить", "Javob beriş", "Reply"),
    "calc_task": ("Рассчитать", "Hisoblaş", "Cost"),
    "confirm_payment": ("Подтвердить", "Tasdiqlaş", "Confirm"),
    "issue_invoice": ("Выставить", "Hisob yoziş", "Issue"),
    "issue_contract": ("Оформить", "Rasmiylaştiriş", "Draw up"),
    "attach_scan": ("Приложить скан", "Skan biriktiriş", "Attach a scan"),
    "issue_act": ("Выпустить акт", "Akt çiqariş", "Issue the act"),
    "supplier_overdue": ("Выяснить", "Aniqlaş", "Find out"),
    "send_supplier_order": ("Отправить", "Yuboriş", "Send"),
    "partner_date_change": ("Решить", "Hal qiliş", "Decide"),
    "receive_goods": ("Принять", "Qabul qiliş", "Receive"),
    "partner_application": ("Рассмотреть", "Körib çiqiş", "Review"),
    "order_shortage": ("Заказать", "Buyurtma beriş", "Order"),
    "ship_project": ("Отгрузить", "Jönatiş", "Ship"),
}

# Нейтральное «почему у вас», когда источник своего факта не дал (вид работы даёт роль).
DEFAULT_REASON: dict[QueueItemKind, tuple[str, str, str]] = {
    "sign_document": (
        "вы подписант по реестру полномочий",
        "siz vakolatlar reyestri böyiça imzolovçisiz",
        "you are a signatory per the authority register",
    ),
    "approve_quote": (
        "ваш шаг одобрения КП",
        "TTni maqullaş böyiça sizning qadamingiz",
        "your quote approval step",
    ),
    "approve_memo": (
        "вы согласующий по маршруту",
        "siz marşrut böyiça kelişuvçisiz",
        "you are an approver on the route",
    ),
    "pay_memo": (
        "ваш шаг: принять к оплате",
        "sizning qadamingiz: tölovga qabul qiliş",
        "your step: accept for payment",
    ),
    "resolve_letter": (
        "входящее без резолюции",
        "rezolyusiyasiz kiruvçi xat",
        "incoming letter without a resolution",
    ),
    "instruction": (
        "поручено вам резолюцией",
        "rezolyusiya bilan sizga topşirilgan",
        "assigned to you by a resolution",
    ),
    "instruction_extension": (
        "вы автор резолюции",
        "siz rezolyusiya muallifisiz",
        "you wrote the resolution",
    ),
    "acquaint": (
        "вас просят ознакомиться",
        "sizdan tanişiş söralmoqda",
        "you are asked to read it",
    ),
    "rework_document": (
        "вам вернули документ",
        "sizga hujjat qaytarildi",
        "a document was returned to you",
    ),
    "answer_lead": (
        "ваш клиент ждёт ответа",
        "sizning mijozingiz javob kutmoqda",
        "your client is waiting for a reply",
    ),
    "take_lead": (
        "лид без менеджера",
        "menejersiz lid",
        "lead without a manager",
    ),
    "triage_lead": (
        "вы первая линия по лидам",
        "lidlar böyiça siz birinçi liniyasiz",
        "you are the first line for leads",
    ),
    "inbound_mail": (
        "общий ящик разбираете вы",
        "umumiy qutini siz saralaysiz",
        "you sort the shared mailbox",
    ),
    "inbound_mail_mine": (
        "письмо в вашей работе",
        "xat sizning işingizda",
        "the email is in your work",
    ),
    "ticket": (
        "обращение сотрудника — вы администратор",
        "xodim murojaati — siz administratorsiz",
        "a staff request — you are the administrator",
    ),
    "calc_task": (
        "расчёт поручен вам",
        "hisob-kitob sizga topşirilgan",
        "the costing is assigned to you",
    ),
    "confirm_payment": (
        "платёжка клиента ждёт подтверждения",
        "mijozning tölov topşiriqnomasi tasdiq kutmoqda",
        "the client's payment order awaits confirmation",
    ),
    "issue_invoice": (
        "счёт ждёт выставления",
        "hisob chiqarilişini kutmoqda",
        "the invoice awaits issuing",
    ),
    "issue_contract": (
        "проект ждёт договор",
        "loyiha şartnomani kutmoqda",
        "the project awaits a contract",
    ),
    "attach_scan": (
        "договор подписан — нужен скан",
        "şartnoma imzolangan — skan kerak",
        "the contract is signed — a scan is needed",
    ),
    "issue_act": (
        "счета оплачены — нужен акт",
        "hisoblar töllangan — akt kerak",
        "invoices are paid — an act is needed",
    ),
    "supplier_overdue": (
        "заказ поставщику просрочен",
        "yetkazib beruvçiga buyurtmaning muddati ötgan",
        "the supplier order is overdue",
    ),
    "send_supplier_order": (
        "заказ ждёт отправки партнёру",
        "buyurtma hamkorga yuborilişini kutmoqda",
        "the order awaits sending to the partner",
    ),
    "partner_date_change": (
        "партнёр просит перенести заказ",
        "hamkor buyurtmani köçiriş söramoqda",
        "the partner asks to move the order",
    ),
    "receive_goods": (
        "заказ ждёт приёмки",
        "buyurtma qabul qilinişini kutmoqda",
        "the order awaits receiving",
    ),
    "partner_application": (
        "заявка на партнёрство",
        "hamkorlik arizasi",
        "partnership application",
    ),
    "order_shortage": (
        "по проекту не заказано всё нужное",
        "loyiha böyiça kerakli narsalar töliq buyurtma qilinmagan",
        "not everything needed for the project is ordered",
    ),
    "ship_project": (
        "товар проекта в резерве",
        "loyiha tovari zaxirada",
        "the project goods are in reserve",
    ),
}


def group_of(label: DueLabel) -> QueueGroup:
    return _GROUP[label]


def finish(item: QueueItem) -> QueueItem:
    """Дописать строке группу, вид работы, глагол и «почему у вас», если источник не задал свои."""
    update: dict[str, object] = {}
    if item.group is None:
        # No fake "today": a row without a real due date is "later" (overdue is the source fact).
        update["group"] = (
            "later"
            if item.due_at is None and item.due_label != "overdue"
            else group_of(item.due_label)
        )
    if item.category is None:
        update["category"] = CATEGORY.get(item.kind, "other")
    if item.action_label is None:
        update["action_label"] = tr(*ACTION.get(item.kind, ("Открыть", "Oçiş", "Open")))
    if item.reason is None:
        update["reason"] = tr(
            *DEFAULT_REASON.get(item.kind, ("по вашей роли", "rolingiz böyiça", "per your role"))
        )
    return item.model_copy(update=update) if update else item

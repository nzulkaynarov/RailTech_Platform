"""Тексты клиентского меню бота и запроса номера телефона (Q-011, Q-020).

Часть ключа `texts` (`TextsSettings` наследует этот класс): вынесены, чтобы
`settings.py` оставался в лимите размера файла. Узбекский — латиница oʻ/gʻ.
"""

from app.schemas.settings_base import CheckedTexts, LocalizedText
from app.schemas.settings_base import localized as _t


class ClientBotTexts(CheckedTexts):
    # Подписи команд в кнопке «Меню» Telegram (до 256 символов, без эмодзи).
    # Выключатель Telegram в центре внешних сервисов (M3-CRM-12, ADR-0024): ответ на любое
    # сообщение, пока исходящие на паузе; не чаще раза в 10 минут на чат.
    maintenance: LocalizedText = _t(
        "Идут технические работы — бот временно не отвечает. Ваше сообщение сохранено, мы ответим, как только закончим.",
        "Texnik ishlar olib borilmoqda — bot vaqtincha javob bermaydi. Xabaringiz saqlandi, ishlarni tugatishimiz bilan javob beramiz.",
        "We are doing maintenance — the bot is temporarily not replying. Your message is saved and we will reply as soon as we are done.",
    )
    menu_start: LocalizedText = _t("Начать", "Boshlash", "Start")
    menu_human: LocalizedText = _t(
        "Связаться с менеджером", "Menejer bilan bogʻlanish", "Talk to a manager"
    )
    menu_lang: LocalizedText = _t("Сменить язык", "Tilni oʻzgartirish", "Change language")
    menu_help: LocalizedText = _t("Что умеет бот", "Bot nimalar qila oladi", "What the bot can do")
    menu_delete: LocalizedText = _t(
        "Удалить переписку", "Yozishmani oʻchirish", "Delete the conversation"
    )
    menu_docs: LocalizedText = _t("Мои документы", "Hujjatlarim", "My documents")
    menu_request: LocalizedText = _t("Запрос менеджеру", "Menejerga soʻrov", "Request to a manager")
    menu_status: LocalizedText = _t("Статус запроса", "Soʻrov holati", "Request status")
    client_only: LocalizedText = _t(
        "Эта команда доступна клиентам компании после заключения договора. Если договор уже есть — нажмите /human, менеджер подключит доступ. Пока я могу ответить на ваши вопросы.",
        "Bu buyruq shartnoma tuzilgandan soʻng kompaniya mijozlari uchun mavjud. Shartnoma boʻlsa — /human tugmasini bosing, menejer kirishni ulab beradi. Hozircha savollaringizga javob berishim mumkin.",
        "This command is available to company clients once a contract is signed. If you already have a contract, tap /human and a manager will connect your access. For now I can answer your questions.",
    )
    # /help по статусу (SPEC §9.2): каждый текст перечисляет ровно команды своего меню.
    help_with_manager: LocalizedText = _t(
        "Вашим вопросом занимается менеджер — пишите сюда, он ответит. Команды: /lang — сменить язык, /delete — удалить переписку.",
        "Savolingiz bilan menejer shugʻullanmoqda — shu yerga yozing, u javob beradi. Buyruqlar: /lang — tilni oʻzgartirish, /delete — yozishmani oʻchirish.",
        "A manager is handling your question — write here and they will reply. Commands: /lang — change language, /delete — delete the conversation.",
    )
    help_client: LocalizedText = _t(
        "Я помогаю клиентам {company}. Команды: /docs — ваши документы, /request — запрос менеджеру, /status — статус запроса, /human — связаться с менеджером, /lang — сменить язык, /delete — удалить переписку.",
        "Men {company} mijozlariga yordam beraman. Buyruqlar: /docs — hujjatlaringiz, /request — menejerga soʻrov, /status — soʻrov holati, /human — menejer bilan bogʻlanish, /lang — tilni oʻzgartirish, /delete — yozishmani oʻchirish.",
        "I help {company} clients. Commands: /docs — your documents, /request — a request to a manager, /status — request status, /human — talk to a manager, /lang — change language, /delete — delete the conversation.",
    )
    client_access_granted: LocalizedText = _t(
        "Теперь вам доступны документы и запросы менеджеру: /docs — ваши документы, /request — новый запрос, /help — все команды.",
        "Endi sizga hujjatlar va menejerga soʻrovlar ochiq: /docs — hujjatlaringiz, /request — yangi soʻrov, /help — barcha buyruqlar.",
        "Documents and requests to a manager are now available to you: /docs — your documents, /request — a new request, /help — all commands.",
    )
    request_text_only: LocalizedText = _t(
        "Опишите запрос текстом одним сообщением. Файл можно отправить после — менеджер его увидит.",
        "Soʻrovni bitta matnli xabarda yozing. Faylni keyin yuborishingiz mumkin — menejer uni koʻradi.",
        "Please describe the request in one text message. You can send the file afterwards and a manager will see it.",
    )
    # Q-022: первое сообщение — выбор языка (текст на всех трёх языках сразу).
    language_first: LocalizedText = _t(
        "Выберите язык общения.",
        "Muloqot tilini tanlang.",
        "Choose your language.",
    )
    handoff_offer_declined: LocalizedText = _t(
        "Хорошо, спрашивайте.", "Yaxshi, savolingizni yozing.", "Okay, go ahead and ask."
    )
    # Q-023: ответ на «дайте телефон/адрес/сайт» — из настроек «Компания», без модели.
    contacts: LocalizedText = _t(
        "Контакты {company}:", "{company} bilan bogʻlanish:", "{company} contacts:"
    )
    contact_labels: LocalizedText = _t(
        "Телефон|Сайт|Адрес", "Telefon|Sayt|Manzil", "Phone|Website|Address"
    )
    contacts_missing: LocalizedText = _t(
        "Контакты подскажет менеджер. Позвать его?",
        "Bogʻlanish maʼlumotlarini menejer aytib beradi. Uni chaqiraymi?",
        "A manager can share the contact details. Shall I call one?",
    )
    sla_promise: LocalizedText = _t(
        "Обычно отвечаем в течение {minutes} минут в рабочее время",
        "Odatda ish vaqtida {minutes} daqiqa ichida javob beramiz",
        "We usually reply within {minutes} minutes during working hours",
    )
    docs_list: LocalizedText = _t(
        "Ваши документы — нажмите, чтобы получить файл:",
        "Hujjatlaringiz — faylni olish uchun bosing:",
        "Your documents — tap one to get the file:",
    )
    docs_choose: LocalizedText = _t(
        "Нашлось несколько документов — выберите нужный:",
        "Bir nechta hujjat topildi — keraklisini tanlang:",
        "I found several documents — choose the one you need:",
    )
    docs_empty: LocalizedText = _t(
        "Пока у вас нет документов в системе. Если документ нужен — напишите /request.",
        "Hozircha tizimda hujjatlaringiz yoʻq. Hujjat kerak boʻlsa — /request yozing.",
        "There are no documents for you yet. If you need one, send /request.",
    )
    request_prompt: LocalizedText = _t(
        "Опишите ваш запрос одним сообщением — я передам его менеджеру.",
        "Soʻrovingizni bitta xabarda yozing — uni menejerga yuboraman.",
        "Describe your request in one message and I'll pass it to a manager.",
    )
    # {number} — номер запроса в CRM.
    request_created: LocalizedText = _t(
        "Запрос №{number} передан менеджеру. Статус — /status.",
        "№{number} soʻrov menejerga yuborildi. Holati — /status.",
        "Request #{number} has been passed to a manager. Check its status: /status.",
    )
    request_status_open: LocalizedText = _t(
        "Запрос №{number} от {date} в работе у менеджера: «{summary}».",
        "{date} sanadagi №{number} soʻrovingiz koʻrib chiqilmoqda: «{summary}».",
        "Request #{number} from {date} is being handled by a manager: “{summary}”.",
    )
    request_status_none: LocalizedText = _t(
        "Открытых запросов нет. Новый запрос — /request.",
        "Ochiq soʻrovlar yoʻq. Yangi soʻrov — /request.",
        "You have no open requests. New request — /request.",
    )
    phone_request: LocalizedText = _t(
        "Чтобы менеджер мог при необходимости позвонить, поделитесь номером телефона кнопкой ниже. Это необязательно.",
        "Menejer kerak boʻlsa qoʻngʻiroq qila olishi uchun quyidagi tugma orqali telefon raqamingizni yuboring. Bu majburiy emas.",
        "So a manager can call you if needed, share your phone number with the button below. This is optional.",
    )
    phone_share_button: LocalizedText = _t(
        "Поделиться номером", "Raqamni yuborish", "Share my number"
    )
    phone_skip_button: LocalizedText = _t("Не сейчас", "Hozir emas", "Not now")
    phone_saved: LocalizedText = _t(
        "Спасибо, номер сохранён.", "Rahmat, raqam saqlandi.", "Thank you, your number is saved."
    )
    phone_skipped: LocalizedText = _t(
        "Хорошо, продолжаем без номера.",
        "Yaxshi, raqamsiz davom etamiz.",
        "Okay, we'll continue without it.",
    )
    phone_before_manager: LocalizedText = _t(
        "Чтобы менеджер мог связаться с вами, поделитесь номером телефона кнопкой ниже — сразу после этого передам ваш вопрос. Это также защищает от спама.",
        "Menejer siz bilan bogʻlana olishi uchun quyidagi tugma orqali telefon raqamingizni yuboring — shundan soʻng savolingizni darhol menejerga beraman. Bu spamdan ham himoya qiladi.",
        "So a manager can contact you, share your phone number with the button below — I will pass your question on right after that. This also protects against spam.",
    )
    phone_declined_manager: LocalizedText = _t(
        "Хорошо, продолжу отвечать сам. Менеджера позову, когда поделитесь номером.",
        "Yaxshi, oʻzim javob berishda davom etaman. Raqamingizni yuborganingizda menejerni chaqiraman.",
        "Okay, I'll keep answering myself. I'll call a manager once you share your number.",
    )
    phone_not_own: LocalizedText = _t(
        "Сохранить можно только ваш собственный номер — кнопкой «Поделиться номером».",
        "Faqat oʻz raqamingizni «Raqamni yuborish» tugmasi orqali saqlash mumkin.",
        "Only your own number can be saved — use the “Share my number” button.",
    )

    # События ERP клиенту (FIX-34, I-8): бот пишет на языке лида. {deal} — название сделки,
    # {number} — номер документа, {amount} {currency} — сумма, {due} — срок оплаты,
    # {summary} — состав поставки, {status} — статус поставки, {eta} — ожидаемая дата.
    erp_quote_sent: LocalizedText = _t(
        "Вам подготовлено коммерческое предложение по сделке «{deal}».",
        "Sizga «{deal}» bitimi boʻyicha tijorat taklifi tayyorlandi.",
        "A commercial proposal for the deal “{deal}” has been prepared for you.",
    )
    erp_invoice_issued: LocalizedText = _t(
        "Выставлен счёт {number} на сумму {amount} {currency}. Срок оплаты: до {due}.",
        "{number}-hisob {amount} {currency} summasida berildi. Toʻlov muddati: {due} gacha.",
        "Invoice {number} for {amount} {currency} has been issued. Due by {due}.",
    )
    erp_invoice_paid: LocalizedText = _t(
        "Поступила оплата по счёту {number} на сумму {amount} {currency}. Спасибо!",
        "{number}-hisob boʻyicha {amount} {currency} toʻlov kelib tushdi. Rahmat!",
        "Payment of {amount} {currency} for invoice {number} has been received. Thank you!",
    )
    erp_delivery_status: LocalizedText = _t(
        "Статус доставки по заказу «{deal}» ({summary}): {status}.",
        "«{deal}» buyurtmasi ({summary}) yetkazib berish holati: {status}.",
        "Delivery status for the order “{deal}” ({summary}): {status}.",
    )
    erp_delivery_statuses: LocalizedText = _t(
        "Собирается|В пути|Готов к отгрузке|Отгружен|Доставлен",
        "Yigʻilmoqda|Yoʻlda|Joʻnatishga tayyor|Joʻnatildi|Yetkazildi",
        "Being assembled|In transit|Ready to ship|Shipped|Delivered",
    )
    erp_delivery_eta_changed: LocalizedText = _t(
        "Срок доставки по заказу «{deal}» ({summary}) обновлён: ожидается {eta}.",
        "«{deal}» buyurtmasi ({summary}) yetkazib berish muddati yangilandi: kutilayotgan sana {eta}.",
        "The delivery date for the order “{deal}” ({summary}) has been updated: expected {eta}.",
    )
    erp_act_issued: LocalizedText = _t(
        "Акт {number} сформирован и ждёт вашего подтверждения в кабинете.",
        "{number}-dalolatnoma shakllantirildi va kabinetda tasdiqlashingizni kutmoqda.",
        "Act {number} has been issued and is waiting for your confirmation in the cabinet.",
    )
    erp_btn_quote: LocalizedText = _t("Открыть КП", "Taklifni ochish", "Open the quote")
    erp_btn_invoice: LocalizedText = _t("Открыть счёт", "Hisobni ochish", "Open the invoice")
    erp_btn_cabinet: LocalizedText = _t("Кабинет", "Kabinet", "Cabinet")

    # События ERP сотруднику (личное сообщение ответственному). {client} — клиент, {quote} —
    # номер КП, {deal} — сделка, {number} — номер акта, {reason} — замечания клиента.
    erp_staff_quote_accepted: LocalizedText = _t(
        "🎉 Клиент «{client}» акцептовал КП #{quote} по сделке «{deal}».",
        "🎉 Mijoz «{client}» «{deal}» bitimi boʻyicha #{quote} tijorat taklifini qabul qildi.",
        "🎉 The client “{client}” accepted quote #{quote} for the deal “{deal}”.",
    )
    erp_staff_act_returned: LocalizedText = _t(
        "⚠️ Акт {number} по сделке «{deal}» возвращён клиентом с замечаниями: {reason}.",
        "⚠️ «{deal}» bitimi boʻyicha {number}-dalolatnoma mijoz tomonidan izoh bilan qaytarildi: {reason}.",
        "⚠️ Act {number} for the deal “{deal}” was returned by the client with remarks: {reason}.",
    )

    # Ход приёмки строк поставки клиентом (FIX-37): запись в ленту лида и личное сообщение ответственному.
    # Уходят на русском. {contact} — контакт клиента, {line} — номер строки, {title} — название строки,
    # {deal} — сделка, {remark} — замечание клиента, {client} — клиент.
    erp_note_delivery_line_accepted: LocalizedText = _t(
        "Клиент ({contact}) принял строку {line} «{title}» по сделке «{deal}».",
        "Mijoz ({contact}) «{deal}» bitimi boʻyicha {line}-qator «{title}»ni qabul qildi.",
        "The client ({contact}) accepted line {line} “{title}” of the deal “{deal}”.",
    )
    erp_note_delivery_line_disputed: LocalizedText = _t(
        "Клиент ({contact}) оспорил строку {line} «{title}» по сделке «{deal}». Замечание: {remark}",
        "Mijoz ({contact}) «{deal}» bitimi boʻyicha {line}-qator «{title}»ga eʼtiroz bildirdi. Izoh: {remark}",
        "The client ({contact}) disputed line {line} “{title}” of the deal “{deal}”. Remark: {remark}",
    )
    erp_staff_delivery_line_disputed: LocalizedText = _t(
        "⚠️ Клиент «{client}» оспорил строку {line} «{title}» по сделке «{deal}»: {remark}",
        "⚠️ Mijoz «{client}» «{deal}» bitimi boʻyicha {line}-qator «{title}»ga eʼtiroz bildirdi: {remark}",
        "⚠️ The client “{client}” disputed line {line} “{title}” of the deal “{deal}”: {remark}",
    )

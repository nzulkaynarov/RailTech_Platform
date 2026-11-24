"""Тексты клиентского меню бота и запроса номера телефона (Q-011, Q-020).

Часть ключа `texts` (`TextsSettings` наследует этот класс): вынесены, чтобы
`settings.py` оставался в лимите размера файла. Узбекский — новая латиница (Ö Ğ Ş Ç).
"""

from app.schemas.settings_base import CheckedTexts, LocalizedText
from app.schemas.settings_base import localized as _t


class ClientBotTexts(CheckedTexts):
    # Подписи команд в кнопке «Меню» Telegram (до 256 символов, без эмодзи).
    # Выключатель Telegram в центре внешних сервисов (M3-CRM-12, ADR-0024): ответ на любое
    # сообщение, пока исходящие на паузе; не чаще раза в 10 минут на чат.
    maintenance: LocalizedText = _t(
        "Идут технические работы — бот временно не отвечает. Ваше сообщение сохранено, мы ответим, как только закончим.",
        "Texnik işlar olib borilmoqda — bot vaqtinça javob bermaydi. Xabaringiz saqlandi, işlarni tugatişimiz bilan javob beramiz.",
        "We are doing maintenance — the bot is temporarily not replying. Your message is saved and we will reply as soon as we are done.",
    )
    menu_start: LocalizedText = _t("Начать", "Boşlaş", "Start")
    menu_human: LocalizedText = _t(
        "Связаться с менеджером", "Menejer bilan boğlaniş", "Talk to a manager"
    )
    menu_lang: LocalizedText = _t("Сменить язык", "Tilni özgartiriş", "Change language")
    menu_help: LocalizedText = _t("Что умеет бот", "Bot nimalar qila oladi", "What the bot can do")
    menu_delete: LocalizedText = _t(
        "Удалить переписку", "Yozişmani öçiriş", "Delete the conversation"
    )
    menu_docs: LocalizedText = _t("Мои документы", "Hujjatlarim", "My documents")
    menu_request: LocalizedText = _t(
        "Обращение менеджеру", "Menejerga murojaat", "Inquiry to a manager"
    )
    menu_status: LocalizedText = _t("Мои обращения", "Murojaatlarim", "My inquiries")
    client_only: LocalizedText = _t(
        "Эта команда доступна клиентам компании после заключения договора. Если договор уже есть — нажмите /human, менеджер подключит доступ. Пока я могу ответить на ваши вопросы.",
        "Bu buyruq şartnoma tuzilgandan söng kompaniya mijozlari uçun mavjud. Şartnoma bölsa — /human tugmasini bosing, menejer kirişni ulab beradi. Hozirça savollaringizga javob berişim mumkin.",
        "This command is available to company clients once a contract is signed. If you already have a contract, tap /human and a manager will connect your access. For now I can answer your questions.",
    )
    # /help по статусу (SPEC §9.2): каждый текст перечисляет ровно команды своего меню.
    help_with_manager: LocalizedText = _t(
        "Вашим вопросом занимается менеджер — пишите сюда, он ответит. Команды: /lang — сменить язык, /delete — удалить переписку.",
        "Savolingiz bilan menejer şuğullanmoqda — şu yerga yozing, u javob beradi. Buyruqlar: /lang — tilni özgartiriş, /delete — yozişmani öçiriş.",
        "A manager is handling your question — write here and they will reply. Commands: /lang — change language, /delete — delete the conversation.",
    )
    help_client: LocalizedText = _t(
        "Я помогаю клиентам {company}. Команды: /docs — ваши документы, /request — обращение менеджеру, /status — мои обращения, /human — связаться с менеджером, /lang — сменить язык, /delete — удалить переписку.",
        "Men {company} mijozlariga yordam beraman. Buyruqlar: /docs — hujjatlaringiz, /request — menejerga murojaat, /status — murojaatlarim, /human — menejer bilan bağlanış, /lang — tilni özgartiriş, /delete — yozişmani öçiriş.",
        "I help {company} clients. Commands: /docs — your documents, /request — an inquiry to a manager, /status — my inquiries, /human — talk to a manager, /lang — change language, /delete — delete the conversation.",
    )
    client_access_granted: LocalizedText = _t(
        "Теперь вам доступны документы и обращения к менеджеру: /docs — ваши документы, /request — новое обращение, /help — все команды.",
        "Endi sizga hujjatlar va menejerga murojaatlar oçiq: /docs — hujjatlaringiz, /request — yangi murojaat, /help — barça buyruqlar.",
        "Documents and inquiries to a manager are now available to you: /docs — your documents, /request — a new inquiry, /help — all commands.",
    )
    request_text_only: LocalizedText = _t(
        "Опишите обращение текстом одним сообщением. Файл можно отправить после — менеджер его увидит.",
        "Murojaatni bitta matnli xabarda yozing. Faylni keyin yuborişingiz mumkin — menejer uni köradi.",
        "Please describe the inquiry in one text message. You can send the file afterwards and a manager will see it.",
    )
    # Q-022: первое сообщение — выбор языка (текст на всех трёх языках сразу).
    language_first: LocalizedText = _t(
        "Выберите язык общения.",
        "Muloqot tilini tanlang.",
        "Choose your language.",
    )
    handoff_offer_declined: LocalizedText = _t(
        "Хорошо, спрашивайте.", "Yaxşi, savolingizni yozing.", "Okay, go ahead and ask."
    )
    # Q-023: ответ на «дайте телефон/адрес/сайт» — из настроек «Компания», без модели.
    contacts: LocalizedText = _t(
        "Контакты {company}:", "{company} bilan boğlaniş:", "{company} contacts:"
    )
    contact_labels: LocalizedText = _t(
        "Телефон|Сайт|Адрес", "Telefon|Sayt|Manzil", "Phone|Website|Address"
    )
    contacts_missing: LocalizedText = _t(
        "Контакты подскажет менеджер. Позвать его?",
        "Boğlaniş maʼlumotlarini menejer aytib beradi. Uni çaqiraymi?",
        "A manager can share the contact details. Shall I call one?",
    )
    sla_promise: LocalizedText = _t(
        "Менеджер ответит в рабочее время",
        "Menejer iş vaqtida javob beradi",
        "A manager will reply during business hours",
    )
    docs_list: LocalizedText = _t(
        "Ваши документы — нажмите, чтобы получить файл:",
        "Hujjatlaringiz — faylni oliş uçun bosing:",
        "Your documents — tap one to get the file:",
    )
    docs_choose: LocalizedText = _t(
        "Нашлось несколько документов — выберите нужный:",
        "Bir neçta hujjat topildi — keraklisini tanlang:",
        "I found several documents — choose the one you need:",
    )
    docs_empty: LocalizedText = _t(
        "Пока у вас нет документов. Если документ нужен — напишите /request.",
        "Hozirça hujjatlaringiz yöq. Hujjat kerak bölsa — /request yozing.",
        "There are no documents for you yet. If you need one, send /request.",
    )
    request_prompt: LocalizedText = _t(
        "Опишите ваше обращение одним сообщением — я передам его менеджеру.",
        "Murojaatingizni bitta xabarda yozing — uni menejerga yuboraman.",
        "Describe your inquiry in one message and I'll pass it to a manager.",
    )
    # {number} — номер обращения.
    request_created: LocalizedText = _t(
        "Обращение №{number} передано менеджеру. Статус — /status.",
        "№{number} murojaat menejerga yuborildi. Holati — /status.",
        "Inquiry #{number} has been passed to a manager. Check its status: /status.",
    )
    request_status_open: LocalizedText = _t(
        "Обращение №{number} от {date} в работе у менеджера: «{summary}».",
        "{date} sanadagi №{number} murojaatingiz körib çiqilmoqda: «{summary}».",
        "Inquiry #{number} from {date} is being handled by a manager: “{summary}”.",
    )
    request_status_none: LocalizedText = _t(
        "Открытых обращений нет. Новое обращение — /request.",
        "Oçiq murojaatlar yöq. Yangi murojaat — /request.",
        "You have no open inquiries. New inquiry — /request.",
    )
    phone_request: LocalizedText = _t(
        "Чтобы менеджер мог при необходимости позвонить, поделитесь номером телефона кнопкой ниже. Это необязательно.",
        "Menejer kerak bölsa qönğiroq qila olişi uçun quyidagi tugma orqali telefon raqamingizni yuboring. Bu majburiy emas.",
        "So a manager can call you if needed, share your phone number with the button below. This is optional.",
    )
    phone_share_button: LocalizedText = _t(
        "Поделиться номером", "Raqamni yuboriş", "Share my number"
    )
    phone_skip_button: LocalizedText = _t("Не сейчас", "Hozir emas", "Not now")
    phone_saved: LocalizedText = _t(
        "Спасибо, номер сохранён.", "Rahmat, raqam saqlandi.", "Thank you, your number is saved."
    )
    phone_skipped: LocalizedText = _t(
        "Хорошо, продолжаем без номера.",
        "Yaxşi, raqamsiz davom etamiz.",
        "Okay, we'll continue without it.",
    )
    phone_before_manager: LocalizedText = _t(
        "Чтобы менеджер мог связаться с вами, поделитесь номером телефона кнопкой ниже — сразу после этого передам ваш вопрос.",
        "Menejer siz bilan bağlana olişi uçun quyidagi tugma orqali telefon raqamingizni yuboring — şundan söng savolingizni menejerga beraman.",
        "So a manager can contact you, share your phone number with the button below — I will pass your question on right after that.",
    )
    phone_declined_manager: LocalizedText = _t(
        "Хорошо, продолжу отвечать сам. Менеджера позову, когда поделитесь номером.",
        "Yaxşi, özim javob berişda davom etaman. Raqamingizni yuborganingizda menejerni çaqiraman.",
        "Okay, I'll keep answering myself. I'll call a manager once you share your number.",
    )
    phone_not_own: LocalizedText = _t(
        "Сохранить можно только ваш собственный номер — кнопкой «Поделиться номером».",
        "Faqat öz raqamingizni «Raqamni yuboriş» tugmasi orqali saqlaş mumkin.",
        "Only your own number can be saved — use the “Share my number” button.",
    )

    # События ERP клиенту (FIX-34, I-8): бот пишет на языке лида. {deal} — название заявки или проекта (клиент слова «сделка» не видит),
    # {number} — номер документа, {amount} {currency} — сумма, {due} — срок оплаты,
    # {summary} — состав поставки, {status} — статус поставки, {eta} — ожидаемая дата.
    erp_quote_sent: LocalizedText = _t(
        "Готово КП по заявке «{deal}».",
        "«{deal}» arizasi böyiça tijorat taklifi tayyor.",
        "A quote for request “{deal}” is ready.",
    )
    # Код акцепта КП в кабинете (FIX-60, Q-FIX22-1): ERP просит бота прислать код контакту в Telegram.
    # {code} — одноразовый код, {minutes} — сколько минут он действует. Код не хранится и не
    # попадает в журнал событий, ленту и логи.
    erp_quote_acceptance_code: LocalizedText = _t(
        "Код для принятия КП по заявке «{deal}»: {code}. Действует {minutes} мин. Никому его не сообщайте.",
        "«{deal}» arizasi böyiça tijorat taklifini qabul qiliş kodi: {code}. {minutes} daqiqa amal qiladi. Uni heç kimga aytmang.",
        "Code to accept the quote for request “{deal}”: {code}. Valid for {minutes} min. Do not share it with anyone.",
    )
    erp_invoice_issued: LocalizedText = _t(
        "Выставлен счёт {number} на сумму {amount} {currency}. Срок оплаты: до {due}.",
        "{number}-hisob {amount} {currency} summasida berildi. Tölov muddati: {due} gaça.",
        "Invoice {number} for {amount} {currency} has been issued. Due by {due}.",
    )
    erp_invoice_paid: LocalizedText = _t(
        "Поступила оплата по счёту {number} на сумму {amount} {currency}. Спасибо!",
        "{number}-hisob böyiça {amount} {currency} tölov kelib tuşdi. Rahmat!",
        "Payment of {amount} {currency} for invoice {number} has been received. Thank you!",
    )
    erp_delivery_status: LocalizedText = _t(
        "Поставка по проекту «{deal}» ({summary}): {status}.",
        "«{deal}» loyihasi böyiça yetkazib beriş ({summary}): {status}.",
        "Delivery for project “{deal}” ({summary}): {status}.",
    )
    erp_delivery_statuses: LocalizedText = _t(
        "Комплектуем|В пути|Готово к отгрузке|Отгружено|Доставлено",
        "Yiğilmoqda|Yölda|Jönatişga tayyor|Jönatildi|Yetkazildi",
        "Being assembled|In transit|Ready to ship|Shipped|Delivered",
    )
    erp_delivery_eta_changed: LocalizedText = _t(
        "Срок поставки по проекту «{deal}» ({summary}) изменился: ожидается {eta}.",
        "«{deal}» loyihasi ({summary}) böyiça yetkazib beriş muddati özgardi: kutilayotgan sana {eta}.",
        "The delivery date for project “{deal}” ({summary}) has changed: expected {eta}.",
    )
    erp_act_issued: LocalizedText = _t(
        "Акт {number} ждёт приёмки в кабинете.",
        "{number}-dalolatnoma kabinetda qabul qilinişini kutmoqda.",
        "Act {number} awaits your acceptance in your account.",
    )
    erp_btn_quote: LocalizedText = _t("Открыть КП", "Taklifni oçiş", "Open the quote")
    erp_btn_invoice: LocalizedText = _t("Открыть счёт", "Hisobni oçiş", "Open the invoice")
    erp_btn_cabinet: LocalizedText = _t("Кабинет", "Kabinet", "Account")

    # События ERP сотруднику (личное сообщение ответственному). {client} — клиент, {quote} —
    # номер КП, {deal} — сделка, {number} — номер акта, {reason} — замечания клиента.
    erp_staff_quote_accepted: LocalizedText = _t(
        "🎉 Клиент «{client}» акцептовал КП #{quote} по сделке «{deal}».",
        "🎉 Mijoz «{client}» «{deal}» bitimi böyiça #{quote} tijorat taklifini qabul qildi.",
        "🎉 The client “{client}” accepted quote #{quote} for the deal “{deal}”.",
    )
    erp_staff_act_returned: LocalizedText = _t(
        "⚠️ Акт {number} по сделке «{deal}» возвращён клиентом с замечаниями: {reason}.",
        "⚠️ «{deal}» bitimi böyiça {number}-dalolatnoma mijoz tomonidan izoh bilan qaytarildi: {reason}.",
        "⚠️ Act {number} for the deal “{deal}” was returned by the client with remarks: {reason}.",
    )

    # Ход приёмки строк поставки клиентом (FIX-37): запись в ленту лида и личное сообщение ответственному.
    # Уходят на русском. {contact} — контакт клиента, {line} — номер строки, {title} — название строки,
    # {deal} — сделка, {remark} — замечание клиента, {client} — клиент.
    erp_note_delivery_line_accepted: LocalizedText = _t(
        "Клиент ({contact}) принял строку {line} «{title}» по сделке «{deal}».",
        "Mijoz ({contact}) «{deal}» bitimi böyiça {line}-qator «{title}»ni qabul qildi.",
        "The client ({contact}) accepted line {line} “{title}” of the deal “{deal}”.",
    )
    erp_note_delivery_line_disputed: LocalizedText = _t(
        "Клиент ({contact}) оспорил строку {line} «{title}» по сделке «{deal}». Замечание: {remark}",
        "Mijoz ({contact}) «{deal}» bitimi böyiça {line}-qator «{title}»ga eʼtiroz bildirdi. Izoh: {remark}",
        "The client ({contact}) disputed line {line} “{title}” of the deal “{deal}”. Remark: {remark}",
    )
    erp_staff_delivery_line_disputed: LocalizedText = _t(
        "⚠️ Клиент «{client}» оспорил строку {line} «{title}» по сделке «{deal}»: {remark}",
        "⚠️ Mijoz «{client}» «{deal}» bitimi böyiça {line}-qator «{title}»ga eʼtiroz bildirdi: {remark}",
        "⚠️ The client “{client}” disputed line {line} “{title}” of the deal “{deal}”: {remark}",
    )

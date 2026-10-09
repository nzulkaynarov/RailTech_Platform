"""Схемы настроек (`settings`, SPEC §5.7). Значения по умолчанию — seed.

Каждый ключ — отдельная строка таблицы `settings`; значение валидируется своей
моделью. Тексты бота — в трёх языках (CLAUDE.md §11).
"""

from datetime import date, time
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domain.business_hours import BusinessHours
from app.domain.triggers import TriggerCode, TriggerSettings

Language = Literal["ru", "uz", "en"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalizedText(_Strict):
    ru: str
    uz: str
    en: str

    def get(self, language: Language, **params: str) -> str:
        template: str = getattr(self, language)
        return template.format(**params) if params else template


def _t(ru: str, uz: str, en: str) -> LocalizedText:
    return LocalizedText(ru=ru, uz=uz, en=en)


class CompanySettings(_Strict):
    name: str = "RailTech"
    crm_base_url: str = "http://localhost"


class BusinessHoursSettings(_Strict):
    timezone: str = "Asia/Tashkent"
    start: time = time(9, 0)
    end: time = time(18, 0)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    holidays: list[date] = Field(default_factory=list)

    def domain(self) -> BusinessHours:
        return BusinessHours(
            timezone=self.timezone,
            start=self.start,
            end=self.end,
            weekdays=frozenset(self.weekdays),
            holidays=frozenset(self.holidays),
        )


class TextsSettings(_Strict):
    consent_version: str = "2026-10-08"
    greeting: LocalizedText = _t(
        "Здравствуйте! Я ассистент компании {company}. Отвечаю на вопросы о наших продуктах и услугах и, если нужно, подключу коллегу.",
        "Assalomu alaykum! Men {company} kompaniyasining yordamchisiman. Mahsulot va xizmatlarimiz haqidagi savollarga javob beraman, kerak bo'lsa, hamkasbimni ulayman.",
        "Hello! I'm the {company} assistant. I answer questions about our products and services and can connect you with a colleague when needed.",
    )
    consent: LocalizedText = _t(
        "Чтобы продолжить, подтвердите согласие на обработку персональных данных. Переписка хранится в системе компании и обрабатывается внешними ИИ-сервисами для подготовки ответов. Удалить переписку можно в любой момент командой /delete.",
        "Davom etish uchun shaxsiy ma'lumotlarni qayta ishlashga roziligingizni tasdiqlang. Yozishmalar kompaniya tizimida saqlanadi va javoblarni tayyorlash uchun tashqi sun'iy intellekt xizmatlari tomonidan qayta ishlanadi. Yozishmalarni istalgan vaqtda /delete buyrug'i bilan o'chirishingiz mumkin.",
        "To continue, please confirm your consent to the processing of personal data. The conversation is stored in the company's system and processed by external AI services to prepare answers. You can delete the conversation at any time with /delete.",
    )
    consent_button: LocalizedText = _t("Согласен", "Roziman", "I agree")
    consent_accepted: LocalizedText = _t(
        "Спасибо! Задайте ваш вопрос.",
        "Rahmat! Savolingizni yozing.",
        "Thank you! Please ask your question.",
    )
    consent_accepted_pending: LocalizedText = _t(
        "Спасибо! Отвечаю на ваш вопрос.",
        "Rahmat! Savolingizga javob beraman.",
        "Thank you! Answering your question.",
    )
    consent_decline_button: LocalizedText = _t("Не согласен", "Rozi emasman", "I don't agree")
    consent_declined: LocalizedText = _t(
        "Понимаю. Без согласия я не могу отвечать на вопросы. Если передумаете — нажмите «Согласен»"
        " выше или напишите /start. Удалить уже отправленные сообщения — /delete.",
        "Tushunarli. Roziliksiz savollarga javob bera olmayman. Fikringiz o'zgarsa — yuqoridagi"
        " «Roziman» tugmasini bosing yoki /start yozing. Yuborilgan xabarlarni o'chirish — /delete.",
        "Understood. Without consent I can't answer questions. If you change your mind, press"
        " «I agree» above or type /start. To delete messages already sent, use /delete.",
    )
    consent_required: LocalizedText = _t(
        "Пожалуйста, сначала подтвердите согласие кнопкой ниже.",
        "Iltimos, avval quyidagi tugma orqali roziligingizni tasdiqlang.",
        "Please confirm your consent with the button below first.",
    )
    handoff: LocalizedText = _t(
        "Передаю ваш вопрос коллеге — он свяжется с вами здесь в ближайшее время.",
        "Savolingizni hamkasbimga topshiraman — u tez orada shu yerda siz bilan bog'lanadi.",
        "I'm passing your question to a colleague who will reply here shortly.",
    )
    off_hours: LocalizedText = _t(
        "Передаю ваш вопрос коллеге. Сейчас нерабочее время: мы работаем пн–пт с 9:00 до 18:00 по Ташкенту и ответим в ближайшее рабочее время.",
        "Savolingizni hamkasbimga topshiraman. Hozir ish vaqti emas: biz dushanba–juma, Toshkent vaqti bilan 9:00 dan 18:00 gacha ishlaymiz va eng yaqin ish vaqtida javob beramiz.",
        "I'm passing your question to a colleague. It's outside working hours now: we work Mon–Fri, 9:00–18:00 Tashkent time, and will reply during the next working hours.",
    )
    waiting_for_manager: LocalizedText = _t(
        "Ваше сообщение передано коллеге, он скоро ответит.",
        "Xabaringiz hamkasbimga yetkazildi, u tez orada javob beradi.",
        "Your message has been passed to a colleague, who will reply soon.",
    )
    fallback: LocalizedText = _t(
        "Точного ответа на этот вопрос у меня нет — уточню у коллег. Если хотите, могу передать вопрос менеджеру.",
        "Bu savolga aniq javobim yo'q — hamkasblarimdan aniqlayman. Xohlasangiz, savolni menejerga topshirishim mumkin.",
        "I don't have an exact answer to that — I'll check with my colleagues. If you like, I can pass your question to a manager.",
    )
    handoff_offer_yes: LocalizedText = _t(
        "Передать менеджеру", "Menejerga topshirish", "Pass to a manager"
    )
    handoff_offer_no: LocalizedText = _t("Не нужно", "Kerak emas", "No, thanks")
    help: LocalizedText = _t(
        "Я отвечаю на вопросы о продуктах {company}. Команды: /lang — сменить язык, /human — позвать сотрудника, /delete — удалить переписку.",
        "Men {company} mahsulotlari haqidagi savollarga javob beraman. Buyruqlar: /lang — tilni o'zgartirish, /human — xodimni chaqirish, /delete — yozishmani o'chirish.",
        "I answer questions about {company} products. Commands: /lang — change language, /human — call a person, /delete — delete the conversation.",
    )
    rate_limited: LocalizedText = _t(
        "Вы отправляете сообщения слишком часто. Пожалуйста, подождите минуту.",
        "Siz xabarlarni juda tez yuboryapsiz. Iltimos, bir daqiqa kuting.",
        "You're sending messages too quickly. Please wait a minute.",
    )
    erase_confirm: LocalizedText = _t(
        "Удалить всю переписку с нами? Это действие нельзя отменить.",
        "Biz bilan barcha yozishmalarni o'chiraymi? Bu amalni qaytarib bo'lmaydi.",
        "Delete your whole conversation with us? This cannot be undone.",
    )
    erase_button: LocalizedText = _t("Удалить", "O'chirish", "Delete")
    cancel_button: LocalizedText = _t("Отмена", "Bekor qilish", "Cancel")
    erase_cancelled: LocalizedText = _t(
        "Хорошо, ничего не удаляю.", "Yaxshi, hech narsa o'chirilmadi.", "OK, nothing was deleted."
    )
    erased: LocalizedText = _t(
        "Ваша переписка удалена. Если захотите продолжить, просто напишите снова.",
        "Yozishmangiz o'chirildi. Davom etmoqchi bo'lsangiz, shunchaki qayta yozing.",
        "Your conversation has been deleted. If you want to continue, just write again.",
    )
    document_sent: LocalizedText = _t(
        "Отправляю документ: {title}.",
        "Hujjatni yuboraman: {title}.",
        "Sending the document: {title}.",
    )
    document_failed: LocalizedText = _t(
        "Не получилось отправить файл. Попробуйте запросить его ещё раз чуть позже.",
        "Faylni yuborib bo'lmadi. Birozdan keyin qayta so'rab ko'ring.",
        "I couldn't send the file. Please ask for it again a bit later.",
    )
    manager_joined: LocalizedText = _t(
        "Здравствуйте! Вашим вопросом занимается {manager}, ответ придёт в этот чат.",
        "Assalomu alaykum! Savolingiz bilan {manager} shug'ullanmoqda, javob shu chatga keladi.",
        "Hello! {manager} is now handling your request and will reply in this chat.",
    )
    service_request_closed: LocalizedText = _t(
        "По вашему запросу «{summary}»: {resolution}",
        "«{summary}» so'rovingiz bo'yicha: {resolution}",
        "Regarding your request “{summary}”: {resolution}",
    )
    returned_to_bot: LocalizedText = _t(
        "Снова на связи ассистент {company}. Если понадобится коллега, напишите /human.",
        "Yana {company} yordamchisi aloqada. Hamkasb kerak bo'lsa, /human deb yozing.",
        "The {company} assistant is back. If you need a colleague, type /human.",
    )
    attachment_received: LocalizedText = _t(
        "Спасибо, файл получен. Передам его коллеге.",
        "Rahmat, fayl qabul qilindi. Uni hamkasbimga topshiraman.",
        "Thanks, file received. I'll pass it to a colleague.",
    )
    unsupported_message: LocalizedText = _t(
        "Пока я понимаю только текст, файлы и голосовые. Напишите, пожалуйста, ваш вопрос.",
        "Hozircha faqat matn, fayl va ovozli xabarlarni tushunaman. Savolingizni yozing, iltimos.",
        "For now I understand text, files and voice messages only. Please type your question.",
    )
    service_unavailable: LocalizedText = _t(
        "Извините, сейчас не получается ответить. Ваше сообщение сохранено, коллеги его увидят.",
        "Kechirasiz, hozir javob bera olmayapman. Xabaringiz saqlandi, hamkasblarim uni ko'radi.",
        "Sorry, I can't answer right now. Your message has been saved and my colleagues will see it.",
    )
    language_prompt: LocalizedText = _t(
        "Выберите язык общения:", "Muloqot tilini tanlang:", "Choose your language:"
    )
    language_set: LocalizedText = _t(
        "Буду отвечать на русском.", "O'zbek tilida javob beraman.", "I'll reply in English."
    )


class EscalationSettings(_Strict):
    high_score_threshold: int = Field(default=70, ge=0, le=100)
    no_progress_turns: int = Field(default=4, ge=1)
    kb_gap_streak: int = Field(default=2, ge=1)
    qualifier_min_confidence: float = Field(default=0.7, ge=0, le=1)
    sla_minutes: int = Field(default=15, ge=1)
    reminder_minutes: int = Field(default=60, ge=1)
    disabled_triggers: list[str] = Field(default_factory=list)
    human_request_terms: list[str] = Field(
        default_factory=lambda: [
            "оператор",
            "менеджер",
            "человек",
            "сотрудник",
            "позовите",
            "operator",
            "menejer",
            "xodim",
            "odam bilan",
            "manager",
            "human",
            "real person",
        ]
    )

    def triggers(self) -> TriggerSettings:
        known = {c.value for c in TriggerCode}
        return TriggerSettings(
            high_score_threshold=self.high_score_threshold,
            no_progress_turns=self.no_progress_turns,
            kb_gap_streak=self.kb_gap_streak,
            qualifier_min_confidence=self.qualifier_min_confidence,
            disabled=frozenset(TriggerCode(c) for c in self.disabled_triggers if c in known),
        )


class KbSettings(_Strict):
    min_score: float = Field(default=0.55, ge=0, le=1)
    top_k: int = Field(default=6, ge=1, le=10)


class BotSettings(_Strict):
    persona: str = "Вежливый, спокойный ассистент без давления и навязывания; отвечает по делу."
    max_words: int = Field(default=120, ge=20, le=400)
    history_messages: int = Field(default=20, ge=2, le=50)
    rate_limit_per_minute: int = Field(default=20, ge=1)
    unresponsive_days: int = Field(default=7, ge=1, le=90)  # BUSINESS §5: 7 дней


class TermsSettings(_Strict):
    terms: list[str] = Field(default_factory=list)


class NotificationsSettings(_Strict):
    channel_id: int | None = None
    duty_user_ids: list[int] = Field(default_factory=list)


class BudgetSettings(_Strict):
    daily_usd: float = Field(default=10.0, ge=0)
    fallback_model_enabled: bool = True


SETTINGS_MODELS: Final[dict[str, type[BaseModel]]] = {
    "company": CompanySettings,
    "business_hours": BusinessHoursSettings,
    "texts": TextsSettings,
    "escalation": EscalationSettings,
    "kb": KbSettings,
    "bot": BotSettings,
    "competitors": TermsSettings,
    "stop_words": TermsSettings,
    "notifications": NotificationsSettings,
    "budget": BudgetSettings,
}


class AppSettings(_Strict):
    company: CompanySettings = Field(default_factory=CompanySettings)
    business_hours: BusinessHoursSettings = Field(default_factory=BusinessHoursSettings)
    texts: TextsSettings = Field(default_factory=TextsSettings)
    escalation: EscalationSettings = Field(default_factory=EscalationSettings)
    kb: KbSettings = Field(default_factory=KbSettings)
    bot: BotSettings = Field(default_factory=BotSettings)
    competitors: TermsSettings = Field(default_factory=TermsSettings)
    stop_words: TermsSettings = Field(
        default_factory=lambda: TermsSettings(
            terms=[
                "обман",
                "мошенники",
                "жалоба",
                "суд",
                "aldov",
                "firibgar",
                "scam",
                "fraud",
                "lawyer",
            ]
        )
    )
    notifications: NotificationsSettings = Field(default_factory=NotificationsSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)

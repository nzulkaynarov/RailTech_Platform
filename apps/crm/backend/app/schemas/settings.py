"""Схемы настроек (`settings`, SPEC §5.7). Значения по умолчанию — seed.

Каждый ключ — отдельная строка таблицы `settings`; значение валидируется своей
моделью. Тексты бота — в трёх языках (CLAUDE.md §11).
"""

from datetime import date, time
from typing import Final, Literal

from pydantic import BaseModel, Field

from app.domain.business_hours import BusinessHours
from app.domain.qualification import DecisionRole, Timeline
from app.domain.qualification_rules import Fact, QualificationCriteria
from app.domain.triggers import TriggerCode, TriggerSettings
from app.schemas.settings_base import Language, LocalizedText, StrictModel, localized
from app.schemas.settings_client import ClientBotTexts

__all__ = ["AppSettings", "Language", "LocalizedText"]

_t = localized


_DAYS: dict[str, tuple[str, ...]] = {
    "ru": ("пн", "вт", "ср", "чт", "пт", "сб", "вс"),
    "uz": ("dushanba", "seshanba", "chorshanba", "payshanba", "juma", "shanba", "yakshanba"),
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
}
_ZONES: dict[str, dict[str, str]] = {
    "Asia/Tashkent": {"ru": "по Ташкенту", "uz": "Toshkent vaqti bilan", "en": "Tashkent time"},
}


def _day_ranges(days: list[int], names: tuple[str, ...]) -> str:
    """[0,1,2,3,4] → «пн–пт»; [0,2,4] → «пн, ср, пт»."""
    groups: list[list[int]] = []
    for day in days:
        if groups and day == groups[-1][-1] + 1:
            groups[-1].append(day)
        else:
            groups.append([day])
    parts = [
        f"{names[g[0]]}–{names[g[-1]]}" if len(g) > 2 else ", ".join(names[d] for d in g)
        for g in groups
    ]
    return ", ".join(parts)


class CompanySettings(StrictModel):
    name: str = "RailTech"
    crm_base_url: str = "http://localhost"


class BusinessHoursSettings(StrictModel):
    timezone: str = "Asia/Tashkent"
    start: time = time(9, 0)
    end: time = time(18, 0)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4])
    holidays: list[date] = Field(default_factory=list)

    def describe(self, language: Language) -> str:
        """«пн–пт с 9:00 до 18:00 по Ташкенту» на языке лида — для текстов бота."""
        days = _day_ranges(sorted(set(self.weekdays)), _DAYS[language])
        start, end = f"{self.start:%H:%M}".lstrip("0"), f"{self.end:%H:%M}".lstrip("0")
        place = _ZONES.get(self.timezone, {}).get(language, self.timezone)
        if language == "uz":
            return f"{days}, {place} {start} dan {end} gacha"
        if language == "en":
            return f"{days}, {start}–{end} {place}"
        return f"{days} с {start} до {end} {place}"

    def domain(self) -> BusinessHours:
        return BusinessHours(
            timezone=self.timezone,
            start=self.start,
            end=self.end,
            weekdays=frozenset(self.weekdays),
            holidays=frozenset(self.holidays),
        )


class TextsSettings(ClientBotTexts):
    """Тексты бота; меню клиента и запрос номера — в `ClientBotTexts`."""

    # Клиенту человек — всегда «менеджер / menejer / manager» (Q-015). Узбекский — официальная
    # латиница: oʻ/gʻ (U+02BB), тутук-белги ʼ (U+02BC).
    consent_version: str = "2026-10-08"
    greeting: LocalizedText = _t(
        "Здравствуйте! Я ассистент компании {company}. Отвечаю на вопросы о наших продуктах и услугах и, если нужно, подключу менеджера.",
        "Assalomu alaykum! Men {company} kompaniyasining yordamchisiman. Mahsulot va xizmatlarimiz haqidagi savollarga javob beraman, kerak boʻlsa, menejerni ulayman.",
        "Hello! I'm the {company} assistant. I answer questions about our products and services and can connect you with a manager when needed.",
    )
    consent: LocalizedText = _t(
        "Чтобы продолжить, подтвердите согласие на обработку персональных данных. Переписка хранится в системе компании и обрабатывается внешними ИИ-сервисами для подготовки ответов. Удалить переписку можно в любой момент командой /delete.",
        "Davom etish uchun shaxsiy maʼlumotlarni qayta ishlashga roziligingizni tasdiqlang. Yozishmalar kompaniya tizimida saqlanadi va javoblarni tayyorlash uchun tashqi sunʼiy intellekt xizmatlari tomonidan qayta ishlanadi. Yozishmalarni istalgan vaqtda /delete buyrugʻi bilan oʻchirishingiz mumkin.",
        "To continue, please confirm your consent to the processing of personal data. The conversation is stored in the company's system and processed by external AI services to prepare answers. You can delete the conversation at any time with /delete.",
    )
    consent_button: LocalizedText = _t("Даю согласие", "Roziman", "I agree")
    consent_accepted: LocalizedText = _t(
        "Спасибо! Задайте ваш вопрос.",
        "Rahmat! Savolingizni yozing.",
        "Thank you! Please ask your question.",
    )
    consent_accepted_pending: LocalizedText = _t(
        "Спасибо! Отвечаю на ваш вопрос.",
        "Rahmat! Savolingizga javob beraman.",
        "Thank you! Let me answer your question.",
    )
    consent_decline_button: LocalizedText = _t("Не даю согласия", "Rozi emasman", "I don't agree")
    consent_declined: LocalizedText = _t(
        "Понимаю. Без согласия я не могу отвечать на вопросы. Если передумаете — нажмите"
        " «Даю согласие» выше или напишите /start. Удалить уже отправленные сообщения — /delete.",
        "Tushunarli. Roziliksiz savollarga javob bera olmayman. Fikringiz oʻzgarsa — yuqoridagi"
        " «Roziman» tugmasini bosing yoki /start yozing. Yuborilgan xabarlarni oʻchirish — /delete.",
        "Understood. Without consent I can't answer questions. If you change your mind, tap"
        " “I agree” above or type /start. To delete messages already sent, use /delete.",
    )
    consent_required: LocalizedText = _t(
        "Пожалуйста, сначала подтвердите согласие кнопкой ниже.",
        "Iltimos, avval quyidagi tugma orqali roziligingizni tasdiqlang.",
        "Please confirm your consent with the button below first.",
    )
    handoff: LocalizedText = _t(
        "Передаю ваш вопрос менеджеру — он ответит здесь в ближайшее время.",
        "Savolingizni menejerga yuboraman — u tez orada shu yerda javob beradi.",
        "I'm passing your question to a manager, who will reply here shortly.",
    )
    # {hours} подставляет код из «Рабочих часов» — текст не расходится с настройкой.
    off_hours: LocalizedText = _t(
        "Передаю ваш вопрос менеджеру. Сейчас нерабочее время: мы работаем {hours} и ответим в ближайшее рабочее время.",
        "Savolingizni menejerga yuboraman. Hozir ish vaqti emas: biz {hours} ishlaymiz va eng yaqin ish vaqtida javob beramiz.",
        "I'm passing your question to a manager. It's outside working hours now: we work {hours} and will reply as soon as we're back.",
    )
    waiting_for_manager: LocalizedText = _t(
        "Ваше сообщение передано менеджеру, он скоро ответит.",
        "Xabaringiz menejerga yuborildi, u tez orada javob beradi.",
        "Your message has been passed to a manager, who will reply soon.",
    )
    # Честно: ответа нет, вернуться с ним бот не может — предлагаем менеджера (Q-016).
    fallback: LocalizedText = _t(
        "В моих материалах нет точного ответа на этот вопрос. Передать его менеджеру? Он ответит здесь же.",
        "Materiallarimda bu savolga aniq javob yoʻq. Savolni menejerga yuboraymi? U shu yerda javob beradi.",
        "I don't have a reliable answer to that in my materials. Shall I pass it to a manager? They'll reply right here.",
    )
    handoff_offer_yes: LocalizedText = _t(
        "Позвать менеджера", "Menejerni chaqirish", "Talk to a manager"
    )
    handoff_offer_no: LocalizedText = _t("Не нужно", "Kerak emas", "No, thanks")
    help: LocalizedText = _t(
        "Я отвечаю на вопросы о продуктах {company}. Команды: /lang — сменить язык, /human — связаться с менеджером, /delete — удалить переписку.",
        "Men {company} mahsulotlari haqidagi savollarga javob beraman. Buyruqlar: /lang — tilni oʻzgartirish, /human — menejer bilan bogʻlanish, /delete — yozishmani oʻchirish.",
        "I answer questions about {company} products. Commands: /lang — change language, /human — talk to a manager, /delete — delete the conversation.",
    )
    rate_limited: LocalizedText = _t(
        "Получил много сообщений подряд — дайте мне минуту, и продолжим.",
        "Ketma-ket koʻp xabar keldi — bir daqiqa kuting, keyin davom etamiz.",
        "I've received a lot of messages in a row — give me a minute and we'll continue.",
    )
    erase_confirm: LocalizedText = _t(
        "Удалить всю переписку с нами? Это действие нельзя отменить.",
        "Biz bilan barcha yozishmalarni oʻchiraymi? Bu amalni qaytarib boʻlmaydi.",
        "Delete your whole conversation with us? This cannot be undone.",
    )
    erase_button: LocalizedText = _t("Удалить", "Oʻchirish", "Delete")
    cancel_button: LocalizedText = _t("Отмена", "Bekor qilish", "Cancel")
    erase_cancelled: LocalizedText = _t(
        "Хорошо, ничего не удаляю.", "Yaxshi, hech narsa oʻchirilmadi.", "OK, nothing was deleted."
    )
    erased: LocalizedText = _t(
        "Ваша переписка удалена. Если захотите продолжить, просто напишите снова.",
        "Yozishmangiz oʻchirildi. Davom etmoqchi boʻlsangiz, shunchaki qayta yozing.",
        "Your conversation has been deleted. If you want to continue, just write again.",
    )
    document_sent: LocalizedText = _t(
        "Отправляю документ: {title}.",
        "Hujjatni yuboraman: {title}.",
        "Sending the document: {title}.",
    )
    document_failed: LocalizedText = _t(
        "Не получилось отправить файл. Попробуйте запросить его ещё раз чуть позже.",
        "Faylni yuborib boʻlmadi. Birozdan keyin qayta soʻrab koʻring.",
        "I couldn't send the file. Please ask for it again a bit later.",
    )
    manager_joined: LocalizedText = _t(
        "Здравствуйте! Вашим вопросом занимается {manager}, ответ придёт в этот чат.",
        "Assalomu alaykum! Savolingiz bilan {manager} shugʻullanmoqda, javob shu chatga keladi.",
        "Hello! {manager} is now handling your request and will reply in this chat.",
    )
    service_request_closed: LocalizedText = _t(
        "По вашему запросу «{summary}»: {resolution}",
        "«{summary}» soʻrovingiz boʻyicha: {resolution}",
        "Regarding your request “{summary}”: {resolution}",
    )
    returned_to_bot: LocalizedText = _t(
        "Снова на связи ассистент {company}. Если понадобится менеджер, напишите /human.",
        "Yana {company} yordamchisi aloqada. Menejer kerak boʻlsa, /human deb yozing.",
        "The {company} assistant is back. If you need a manager, type /human.",
    )
    # И для голосовых: бот их не распознаёт, а передаёт менеджеру вложением.
    attachment_received: LocalizedText = _t(
        "Спасибо, получил. Передам менеджеру.",
        "Rahmat, qabul qildim. Menejerga yuboraman.",
        "Thanks, got it. I'll pass it to a manager.",
    )
    unsupported_message: LocalizedText = _t(
        "Я понимаю текст, а файлы и голосовые сообщения передаю менеджеру. Напишите, пожалуйста, ваш вопрос.",
        "Men matnni tushunaman, fayl va ovozli xabarlarni esa menejerga yuboraman. Savolingizni yozing, iltimos.",
        "I can read text; files and voice messages I pass on to a manager. Please type your question.",
    )
    service_unavailable: LocalizedText = _t(
        "Извините, сейчас не получается ответить. Ваше сообщение сохранено, менеджер его увидит.",
        "Kechirasiz, hozir javob bera olmayapman. Xabaringiz saqlandi, menejer uni koʻradi.",
        "Sorry, I can't answer right now. Your message has been saved and a manager will see it.",
    )
    language_prompt: LocalizedText = _t(
        "Выберите язык общения:", "Muloqot tilini tanlang:", "Choose your language:"
    )
    language_set: LocalizedText = _t(
        "Буду отвечать на русском.", "Oʻzbek tilida javob beraman.", "I'll reply in English."
    )


class EscalationSettings(StrictModel):
    high_score_threshold: int = Field(default=70, ge=0, le=100)
    no_progress_turns: int = Field(default=4, ge=1)
    kb_gap_streak: int = Field(default=2, ge=1)
    qualifier_min_confidence: float = Field(default=0.7, ge=0, le=1)
    sla_minutes: int = Field(default=15, ge=1)
    reminder_minutes: int = Field(default=60, ge=1)
    disabled_triggers: list[str] = Field(default_factory=list)
    # Любой вопрос о цене — менеджеру, даже если бот назвал цену из прайса (ADR-0016).
    price_always_to_manager: bool = False
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
            price_always_to_manager=self.price_always_to_manager,
            disabled=frozenset(TriggerCode(c) for c in self.disabled_triggers if c in known),
        )


class KbSettings(StrictModel):
    min_score: float = Field(default=0.55, ge=0, le=1)
    top_k: int = Field(default=6, ge=1, le=10)


class BotSettings(StrictModel):
    persona: str = "Вежливый, спокойный ассистент без давления и навязывания; отвечает по делу."
    max_words: int = Field(default=120, ge=20, le=400)
    history_messages: int = Field(default=20, ge=2, le=50)
    rate_limit_per_minute: int = Field(default=20, ge=1)
    unresponsive_days: int = Field(default=7, ge=1, le=90)  # BUSINESS §5: 7 дней
    # Q-020: один раз предложить «Поделиться номером» (квалификация или запрос менеджера).
    ask_phone: bool = True
    # Q-019: ИИ-помощь менеджеру при ответе («Черновик», «Улучшить») — только по кнопке.
    assist_enabled: bool = True
    assist_max_input_chars: int = Field(default=2000, ge=200, le=4000)


class TermsSettings(StrictModel):
    terms: list[str] = Field(default_factory=list)


class NotificationsSettings(StrictModel):
    channel_id: int | None = None
    duty_user_ids: list[int] = Field(default_factory=list)
    manager_dm_throttle_minutes: int = Field(
        default=5,
        ge=1,
        le=1440,
        description="Не чаще одного личного сообщения менеджеру по лиду за это число минут",
    )


_REQUIRED_FACTS: Final[tuple[Fact, ...]] = ("need", "product")
_ANY_OF_FACTS: Final[tuple[Fact, ...]] = ("timeline", "decision_role", "budget")
_ROLES: Final[tuple[DecisionRole, ...]] = ("decision_maker", "influencer", "researcher")


class QualificationSettings(StrictModel):
    """Когда лид «Квалифицирован» (ADR-0016). По умолчанию — BUSINESS §5."""

    required_facts: list[Fact] = Field(default_factory=lambda: list(_REQUIRED_FACTS))
    any_of_facts: list[Fact] = Field(default_factory=lambda: list(_ANY_OF_FACTS))
    min_any_of: int = Field(default=1, ge=0, le=6)
    timeline_max: Timeline = ">12m"
    decision_roles: list[DecisionRole] = Field(default_factory=lambda: list(_ROLES))

    def criteria(self) -> QualificationCriteria:
        return QualificationCriteria(
            required=frozenset(self.required_facts),
            any_of=frozenset(self.any_of_facts),
            min_any_of=self.min_any_of,
            timeline_max=self.timeline_max,
            decision_roles=frozenset(self.decision_roles),
        )


class ProviderLimitsSettings(StrictModel):
    """Дневной лимит по провайдеру (USD, сутки по Ташкенту, 0 — без лимита), Q-008.

    Ключ — провайдер LiteLLM (префикс модели `anthropic/…`, `gemini/…`). Проверяет наш код перед
    вызовом; потолок `provider_budget_config` в infra/litellm.config.yaml — аварийный, выше.
    """

    anthropic: float = Field(default=3.0, ge=0)
    gemini: float = Field(default=1.0, ge=0)


class BudgetSettings(StrictModel):
    # Ниже жёсткого потолка Anthropic ($3, infra/litellm.config.yaml): диалог уходит на fallback-model
    # раньше, чем провайдер начнёт отклонять запросы (решение владельца Q-008, 2026-10-12).
    daily_usd: float = Field(default=2.0, ge=0)
    fallback_model_enabled: bool = True
    # Сверх лимита провайдера диалог → fallback-model (если его провайдер в лимите), иначе — отказ.
    providers: ProviderLimitsSettings = Field(default_factory=ProviderLimitsSettings)


_LOST_REASONS: Final = ("Дорого", "Выбрали конкурента", "Нет бюджета", "Не актуально")
_LOST_REASONS_TAIL: Final = ("Не вышли на связь", "Другое")


class DealsSettings(StrictModel):
    """Справочник причин отказа и валюта новых сделок (Q-013, ADR-0019)."""

    lost_reasons: list[str] = Field(
        default_factory=lambda: [*_LOST_REASONS, *_LOST_REASONS_TAIL], min_length=1
    )
    currency: str = Field(default="UZS", pattern="^[A-Z]{3}$")


SETTINGS_MODELS: Final[dict[str, type[BaseModel]]] = {
    "company": CompanySettings,
    "business_hours": BusinessHoursSettings,
    "texts": TextsSettings,
    "escalation": EscalationSettings,
    "qualification": QualificationSettings,
    "kb": KbSettings,
    "bot": BotSettings,
    "competitors": TermsSettings,
    "stop_words": TermsSettings,
    "notifications": NotificationsSettings,
    "budget": BudgetSettings,
    "deals": DealsSettings,
}


class AppSettings(StrictModel):
    company: CompanySettings = Field(default_factory=CompanySettings)
    business_hours: BusinessHoursSettings = Field(default_factory=BusinessHoursSettings)
    texts: TextsSettings = Field(default_factory=TextsSettings)
    escalation: EscalationSettings = Field(default_factory=EscalationSettings)
    qualification: QualificationSettings = Field(default_factory=QualificationSettings)
    kb: KbSettings = Field(default_factory=KbSettings)
    bot: BotSettings = Field(default_factory=BotSettings)
    competitors: TermsSettings = Field(default_factory=TermsSettings)
    stop_words: TermsSettings = Field(
        default_factory=lambda: TermsSettings(
            # «основа*» — любая словоформа (узбекский и русский агглютинируют/склоняют).
            terms=[
                "обман*",
                "мошенни*",
                "жалоб*",
                "суд",
                "aldov*",
                "firibgar*",
                "scam*",
                "fraud*",
                "lawyer*",
            ]
        )
    )
    notifications: NotificationsSettings = Field(default_factory=NotificationsSettings)
    budget: BudgetSettings = Field(default_factory=BudgetSettings)
    deals: DealsSettings = Field(default_factory=DealsSettings)

    def lead_notice(self, key: Literal["handoff", "off_hours"], language: Language) -> str:
        """Текст лиду при передаче менеджеру; рабочие часы — из настроек."""
        text: LocalizedText = getattr(self.texts, key)
        return text.get(language, hours=self.business_hours.describe(language))

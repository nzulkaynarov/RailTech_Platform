"""UX бота без модели: просьба о менеджере, язык, контакты, ожидание, /help (аудит 2026-10-12)."""

import re
from datetime import UTC, date, datetime

import pytest

from app.bot.handlers import help_text
from app.domain.bot_menu import MENUS, MenuVariant, contact_request
from app.domain.keywords import find_terms
from app.domain.language import Language, detect_language, mismatch_offer, requested_language
from app.schemas.settings import AppSettings, BusinessHoursSettings, CompanySettings

CFG = AppSettings()
HUMAN = CFG.escalation.human_request_terms


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("дай номер менеджера", True),
        ("соедините с менеджером", True),
        ("можно с менеджером связаться?", True),
        ("хочу поговорить с человеком", True),
        ("позовите оператора", True),
        ("нужен живой человек", True),
        ("menejerga ulang", True),
        ("operatorga ulang", True),
        ("odam bilan gaplashmoqchiman", True),
        ("Menejer bilan bogʻlaning", True),
        ("I want to talk to a manager", True),
        ("can I speak to a real person?", True),
        ("human please", True),
        # Не просьба о человеке: сумма людей, «человеческий фактор», персональные данные.
        ("нас будет 5 человек", False),
        ("влияет ли человеческий фактор?", False),
        ("odamlar soni 10 ta", False),
        ("how do you store personal data?", False),
        ("сколько стоит интеграция?", False),
    ],
)
def test_human_request_terms(text: str, expected: bool) -> None:
    assert bool(find_terms(text, HUMAN)) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("на русском", "ru"),
        ("давай по-русски", "ru"),
        ("Можно на русском?", "ru"),
        ("oʻzbekcha", "uz"),
        ("o'zbek tilida gapiring", "uz"),
        ("узбекча", "uz"),
        ("in English", "en"),
        ("english please", "en"),
        ("Как будет «вагон» in English, если мы говорим о поставке", None),
        ("Сколько стоит?", None),
        ("", None),
    ],
)
def test_requested_language(text: str, expected: Language | None) -> None:
    assert requested_language(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Нима керак?", "uz"),
        ("Ассалому алейкум, нарх канча?", "uz"),
        ("рахмат", "uz"),
        ("Сколько стоит интеграция?", "ru"),
        ("Здравствуйте, что вы можете предложить?", "ru"),
    ],
)
def test_uzbek_cyrillic_without_special_letters(text: str, expected: Language) -> None:
    assert detect_language(text) == expected


@pytest.mark.parametrize(
    ("fixed", "detected", "streak", "offered", "expected"),
    [
        ("ru", "ru", 1, False, (0, False)),
        ("ru", "uz", 0, False, (1, False)),
        ("ru", "uz", 1, False, (2, True)),
        ("ru", "uz", 1, True, (2, False)),  # кнопки — один раз
        ("ru", "en", 5, False, (6, True)),
    ],
)
def test_mismatch_offer(
    fixed: Language, detected: Language, streak: int, offered: bool, expected: tuple[int, bool]
) -> None:
    assert mismatch_offer(fixed, detected, streak, offered) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("дайте номер телефона", True),
        ("какой у вас адрес?", True),
        ("Сайт есть?", True),
        ("telefon raqamingiz", True),
        ("manzilingiz qayerda?", True),
        ("what's your phone number?", True),
        ("contacts please", True),
        ("дай номер менеджера", False),  # просьба о менеджере важнее
        ("какой номер договора?", False),
        ("номер моего запроса", False),
        ("сколько стоит интеграция?", False),
    ],
)
def test_contact_request(text: str, expected: bool) -> None:
    assert contact_request(text, HUMAN) is expected


def test_company_contacts_from_settings() -> None:
    assert CFG.company_contacts("ru") is None  # пусто → бот предлагает менеджера
    cfg = AppSettings(company=CompanySettings(phone="+998 71 000-00-00", site="railtech.uz"))
    text = cfg.company_contacts("ru")
    assert text is not None
    assert "Телефон: +998 71 000-00-00" in text
    assert "Сайт: railtech.uz" in text
    assert "Адрес" not in text


TASHKENT_MONDAY_19 = datetime(2026, 10, 12, 14, 0, tzinfo=UTC)  # пн 19:00 по Ташкенту


@pytest.mark.parametrize(
    ("now", "holidays", "language", "expected"),
    [
        (datetime(2026, 10, 12, 2, 0, tzinfo=UTC), [], "ru", "сегодня с 9:00"),
        (TASHKENT_MONDAY_19, [], "ru", "завтра с 9:00"),
        (TASHKENT_MONDAY_19, [date(2026, 10, 13)], "ru", "в среду с 9:00"),
        (datetime(2026, 10, 16, 14, 0, tzinfo=UTC), [], "ru", "в понедельник с 9:00"),
        (datetime(2026, 10, 16, 14, 0, tzinfo=UTC), [], "uz", "dushanba kuni soat 9:00 dan"),
        (TASHKENT_MONDAY_19, [], "en", "tomorrow from 9:00"),
    ],
)
def test_off_hours_names_the_next_working_time(
    now: datetime, holidays: list[date], language: Language, expected: str
) -> None:
    cfg = AppSettings(business_hours=BusinessHoursSettings(holidays=holidays))
    text = cfg.handoff_notice(language, now)
    assert expected in text
    assert not re.search(r"пн–пт|мы работаем", text)  # праздник в будний день не путает


def test_handoff_in_working_time_promises_the_sla() -> None:
    now = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)  # пн 11:00 по Ташкенту
    text = CFG.handoff_notice("ru", now)
    assert text.startswith("Передаю ваш запрос менеджеру")
    assert f"в течение {CFG.escalation.sla_minutes} минут в рабочее время" in text


@pytest.mark.parametrize("variant", ["prospect", "with_manager", "client"])
@pytest.mark.parametrize("language", ["ru", "uz", "en"])
def test_help_lists_exactly_the_menu(variant: MenuVariant, language: Language) -> None:
    mentioned = set(re.findall(r"/(\w+)", help_text(CFG, variant, language)))
    assert mentioned == set(MENUS[variant]) - {"start", "help"}


def test_request_closed_names_the_request() -> None:
    for language in ("ru", "uz", "en"):
        text = CFG.texts.service_request_closed.get(
            language,
            number="17",
            summary="акт",
            resolution="готово",
        )
        assert "17" in text


def test_uzbek_defaults_have_no_ascii_apostrophe() -> None:
    """Узбекская латиница — oʻ/gʻ (U+02BB) во всех текстах настроек, не «o'»/«g'»."""
    offenders = [
        name
        for name, value in CFG.texts
        if hasattr(value, "uz") and re.search(r"[oOgG]['‘’`]", value.uz)
    ]
    assert offenders == []

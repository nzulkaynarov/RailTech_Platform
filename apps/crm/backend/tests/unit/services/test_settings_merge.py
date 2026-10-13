import pytest

from app.domain.language import Language
from app.schemas.settings import AppSettings, BusinessHoursSettings, KbSettings
from app.services.settings import _merge


def test_defaults_without_rows() -> None:
    assert _merge({}) == AppSettings()


def test_row_overrides_key() -> None:
    merged = _merge({"kb": {"min_score": 0.7, "top_k": 4}})
    assert merged.kb == KbSettings(min_score=0.7, top_k=4)
    assert merged.bot == AppSettings().bot


def test_invalid_row_falls_back_to_default() -> None:
    merged = _merge({"kb": {"min_score": 5}})
    assert merged.kb == KbSettings()


def test_localized_text_formatting() -> None:
    texts = AppSettings().texts
    assert "RailTech" in texts.help.get("en", company="RailTech")
    assert texts.consent_button.get("uz") == "Roziman"


def test_all_texts_have_three_languages() -> None:
    texts = AppSettings().texts
    for name, value in texts:
        if name == "consent_version":
            continue
        assert all([value.ru, value.uz, value.en]), name


@pytest.mark.parametrize(
    ("weekdays", "language", "expected"),
    [
        ([0, 1, 2, 3, 4], "ru", "пн–пт с 9:00 до 18:00 по Ташкенту"),
        ([0, 2, 4], "ru", "пн, ср, пт с 9:00 до 18:00 по Ташкенту"),
        ([0, 1, 2, 3, 4, 5], "en", "Mon–Sat, 9:00–18:00 Tashkent time"),
        ([0, 1, 2, 3, 4], "uz", "dushanba–juma, Toshkent vaqti bilan 9:00 dan 18:00 gacha"),
    ],
)
def test_off_hours_text_follows_business_hours(
    weekdays: list[int], language: Language, expected: str
) -> None:
    """Аудит BOT-19: часы работы в тексте лиду берутся из настроек, а не зашиты."""
    cfg = AppSettings(business_hours=BusinessHoursSettings(weekdays=weekdays))
    assert cfg.business_hours.describe(language) == expected
    # Переопределённый админом текст с {hours} по-прежнему получает расписание из настроек.
    custom = cfg.texts.model_copy(
        update={"off_hours": cfg.texts.off_hours.model_copy(update={language: "{hours}"})}
    )
    assert cfg.model_copy(update={"texts": custom}).lead_notice("off_hours", language) == expected

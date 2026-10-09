from app.schemas.settings import AppSettings, KbSettings
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

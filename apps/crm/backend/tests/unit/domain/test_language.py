import pytest

from app.domain.language import detect_language


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Сколько стоит интеграция с 1С?", "ru"),
        ("Здравствуйте, расскажите про кассы", "ru"),
        ("Нарх қанча туради?", "uz"),
        ("Ўзбекистонда ишлайсизларми?", "uz"),
        ("Narxi qancha?", "uz"),
        ("Salom, bu xizmat qanday ishlaydi?", "uz"),
        ("O'zbekistonda yetkazib berasizmi?", "uz"),
        ("Bog‘lanish uchun telefon kerak", "uz"),
        ("vagonlarni kuzatish", "uz"),
        ("Kassani ulash mumkinmi?", "uz"),
        ("Yetkazib berish xizmati bormi", "uz"),
        ("How much does the integration cost?", "en"),
        ("Tracking of wagons", "en"),
        ("GPS monitoring", "en"),
        ("Hello, what do you offer?", "en"),
        ("12345 !!!", "ru"),
        ("", "ru"),
    ],
)
def test_detect_language(text: str, expected: str) -> None:
    assert detect_language(text) == expected


def test_default_is_used_without_letters() -> None:
    assert detect_language("👍", default="en") == "en"

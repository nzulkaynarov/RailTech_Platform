import pytest

from app.domain.numbers import extract_numbers, unsupported_numbers


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Внедрение занимает 3–5 рабочих дней", {"3", "5"}),
        ("с 09:00 до 18:00", {"9", "0", "18"}),
        ("цена 3,50 или 3.5", {"3.5"}),
        ("гарантия 6 месяцев", {"6"}),
        ("без чисел", set()),
        ("1 000 сум", {"1000"}),
    ],
)
def test_extract_numbers(text: str, expected: set[str]) -> None:
    assert extract_numbers(text) == expected


@pytest.mark.parametrize(
    ("reply", "sources", "invented"),
    [
        ("Внедрение займёт 3–5 дней.", ["занимает 3–5 рабочих дней"], set()),
        ("Стоит 500 долларов.", ["Цену рассчитывает менеджер"], {"500"}),
        (
            "Обновление каждые 15 минут, установка 30 минут.",
            ["каждые 15 минут", "за 30 минут"],
            set(),
        ),
        ("Для 2 касс подойдёт.", ["Вопрос клиента: у меня 2 кассы"], set()),
        ("Гарантия 12 месяцев.", ["гарантия 6 месяцев"], {"12"}),
    ],
)
def test_unsupported_numbers(reply: str, sources: list[str], invented: set[str]) -> None:
    assert unsupported_numbers(reply, sources) == invented

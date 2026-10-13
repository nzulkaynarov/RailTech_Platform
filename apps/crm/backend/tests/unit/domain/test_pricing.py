import pytest

from app.domain.pricing import price_quoted, quoted_amounts

PRICE_LIST = "| Пакет | Цена за трекер в месяц |\n| Базовый | 120 000 |\n| Холод | 180 000 |"


@pytest.mark.parametrize(
    ("reply", "fragments", "expected"),
    [
        # Цена из прайса названа — менеджер не обязателен.
        ("Базовый пакет — 120 000 сум за трекер в месяц.", [PRICE_LIST], True),
        ("Paket narxi 180 000 so'm.", [PRICE_LIST], True),
        ("It costs $50 per tracker.", ["Tracker rental: 50 USD per month"], True),
        # Обещание расчёта без суммы — передача.
        ("Цена зависит от пакета, расчёт делает менеджер.", [PRICE_LIST], False),
        # Сумма, которой нет в базе (выдумана или из вопроса), — не считается.
        ("Это стоит около 100 000 сум.", [PRICE_LIST], False),
        # Числа без валюты (сроки, количество) — не цена.
        ("Установка занимает 30 минут, 3–5 рабочих дней.", ["3–5 рабочих дней, 30 минут"], False),
    ],
)
def test_price_quoted(reply: str, fragments: list[str], expected: bool) -> None:
    assert price_quoted(reply, fragments) is expected


def test_amount_normalization() -> None:
    assert quoted_amounts("1 200 000 сум и 1,5 млн сум") == {"1200000", "15"}

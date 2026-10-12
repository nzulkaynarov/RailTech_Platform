import pytest

from app.domain.assist import improve_adds_numbers, may_assist, strip_unsupported


@pytest.mark.parametrize(
    ("assigned", "user", "admin", "expected"),
    [
        (7, 7, False, True),
        (7, 8, False, False),
        (None, 8, False, False),
        (7, 8, True, True),
        (None, 1, True, True),
    ],
)
def test_may_assist(assigned: int | None, user: int, admin: bool, expected: bool) -> None:
    assert may_assist(assigned_user_id=assigned, user_id=user, is_admin=admin) is expected


@pytest.mark.parametrize(
    ("original", "improved", "expected"),
    [
        ("здраствуйте, отправим счет завтра", "Здравствуйте! Отправим счёт завтра.", False),
        ("цена 1 200 000 сум", "Цена — 1 200 000 сум.", False),
        ("цена 1200000 сум", "Цена — 1 200 000 сум.", False),
        ("отправим счет завтра", "Отправим счёт завтра, 15 октября.", True),
        ("стоимость уточню", "Стоимость — 500 $.", True),
        ("доставка 3 дня", "Доставка займёт 3–5 дней.", True),
        ("hello, we send it today", "Hello, we will send it today.", False),
    ],
)
def test_improve_adds_numbers(original: str, improved: str, expected: bool) -> None:
    assert improve_adds_numbers(original, improved) is expected


@pytest.mark.parametrize(
    ("draft", "sources", "text", "removed"),
    [
        (
            "Здравствуйте! Тариф стоит 1 500 000 сум. Пришлём договор.",
            ["Тариф: 1 500 000 сум в месяц"],
            "Здравствуйте! Тариф стоит 1 500 000 сум. Пришлём договор.",
            0,
        ),
        (
            "Здравствуйте! Тариф стоит 900 000 сум. Расчёт сделает менеджер.",
            ["Тариф: 1 500 000 сум в месяц"],
            "Здравствуйте! Расчёт сделает менеджер.",
            1,
        ),
        ("Доставка за 2 дня.", ["клиент: нужна доставка за 2 дня"], "Доставка за 2 дня.", 0),
        ("Цена 100 $.", [], "", 1),
        ("Строка один.\nСтрока 2 без источника.", [], "Строка один.", 1),
        ("Абзац один.\n\nАбзац два.", [], "Абзац один.\n\nАбзац два.", 0),
    ],
)
def test_strip_unsupported(draft: str, sources: list[str], text: str, removed: int) -> None:
    check = strip_unsupported(draft, sources)
    assert (check.text, check.removed) == (text, removed)

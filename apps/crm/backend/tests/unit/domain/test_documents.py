from datetime import date

import pytest

from app.domain.documents import DocQuery, parse

TODAY = date(2026, 10, 8)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Пришлите договор, который мы заключали в июле",
            DocQuery("contract", date(2026, 7, 1), date(2026, 8, 1), None, True),
        ),
        (
            "Нужен счёт за декабрь",
            DocQuery("invoice", date(2025, 12, 1), date(2026, 1, 1), None, True),
        ),
        ("акт за май 2025", DocQuery("act", date(2025, 5, 1), date(2025, 6, 1), None, True)),
        (
            "Iyul oyidagi shartnomani yuboring",
            DocQuery("contract", date(2026, 7, 1), date(2026, 8, 1), None, True),
        ),
        (
            "Send me the invoice from March 2026",
            DocQuery("invoice", date(2026, 3, 1), date(2026, 4, 1), None, True),
        ),
        ("договор № 15/2026", DocQuery("contract", None, None, "15/2026", True)),
        (
            "Все документы за 2025 год",
            DocQuery(None, date(2025, 1, 1), date(2026, 1, 1), None, True),
        ),
        ("Когда приедет инженер в магазин?", DocQuery(None, None, None, None, False)),
        ("Пришлите КП", DocQuery("proposal", None, None, None, True)),
    ],
)
def test_parse(text: str, expected: DocQuery) -> None:
    assert parse(text, TODAY) == expected

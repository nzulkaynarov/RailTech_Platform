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


@pytest.mark.parametrize(
    "text",
    [
        "Какая актуальная цена на RT-Track?",
        "Активный тариф можно поменять?",
        "Xatolik chiqdi, nima qilish kerak?",
        "Как работает billing у вас?",
        "Счётчик вагонов показывает ноль",
        "Договоримся о встрече на завтра?",
        "Где посмотреть профиль компании?",
        "Писал вам вчера, ответа нет",
    ],
)
def test_ordinary_questions_are_not_document_requests(text: str) -> None:
    parsed = parse(text, TODAY)
    assert parsed.is_request is False
    assert parsed.doc_type is None


@pytest.mark.parametrize(
    ("text", "doc_type"),
    [
        ("Нужна копия акта сверки", "act"),
        ("Пришлите акты за квартал", "act"),
        ("Договора за этот год", "contract"),
        ("По контракту № 7", "contract"),
        ("Счета за март", "invoice"),
        ("Hisob-faktura kerak", "invoice"),
        ("Need the bills for May", "invoice"),
        ("Dalolatnomani yuboring", "act"),
        ("Xatni yuboring", "letter"),
        ("Пришлите письмо от банка", "letter"),
        ("Коммерческое предложение от июля", "proposal"),
        ("Taklifni yuboring", "proposal"),
    ],
)
def test_document_word_forms(text: str, doc_type: str) -> None:
    parsed = parse(text, TODAY)
    assert parsed.doc_type == doc_type
    assert parsed.is_request is True

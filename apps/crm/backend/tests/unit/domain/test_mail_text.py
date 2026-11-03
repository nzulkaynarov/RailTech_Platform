"""Текст письма без пустот, цитаты и подписи (W18A-P2-4): тексты и адреса — вымышленные."""

import pytest

from app.domain.mail_text import normalize_text, split_quote

ZW = "‌​͏­﻿"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("a\n\n\n\n\nb", "a\n\nb", id="blank-lines-to-one"),
        pytest.param("a\n \n\t\n \n\nb", "a\n\nb", id="blank-with-spaces"),
        pytest.param("a   b\t\tc", "a b c", id="spaces"),
        pytest.param("a  b c d", "a b c d", id="nbsp-and-unicode-spaces"),
        pytest.param(f"a\n{ZW}\n{ZW}\n{ZW}\nb", "a\n\nb", id="zero-width-padding-lines"),
        pytest.param(f"a{ZW}b", "ab", id="invisible-inside-word"),
        pytest.param("a\r\nb\rc", "a\nb\nc", id="line-endings"),
        pytest.param("\n\n  \nТекст\n\n\n", "Текст", id="trim"),
        pytest.param("a\x00\x07b", "ab", id="control"),
        pytest.param("a b", "a\nb", id="line-separator"),
        pytest.param("", "", id="empty"),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_normalize_text_caps_length() -> None:
    assert len(normalize_text("я" * 80_000)) == 50_000


REPLY = "Добрый день, принято."
EN_ATTR = "On Mon, 2 Nov 2026 at 10:00, Ivan Testov <ivan@example.test> wrote:"
RU_ATTR = "Пн, 2 нояб. 2026 г. в 10:00, Иван Тестов <ivan@example.test> пишет:"


@pytest.mark.parametrize(
    ("raw", "main", "tail"),
    [
        pytest.param("Привет\nмир", "Привет\nмир", "", id="no-quote"),
        pytest.param(
            f"{REPLY}\n\n{EN_ATTR}\n> Нужен счёт\n> на 10 шпал",
            REPLY,
            f"{EN_ATTR}\n> Нужен счёт\n> на 10 шпал",
            id="en-attribution-gt",
        ),
        pytest.param(
            f"{REPLY}\n\n{RU_ATTR}\n> Нужен счёт",
            REPLY,
            f"{RU_ATTR}\n> Нужен счёт",
            id="ru-attribution-gt",
        ),
        pytest.param(
            f"{REPLY}\n\nOn Mon, 2 Nov 2026 at 10:00, Ivan Testov <ivan@example.test>\nwrote:\n> q",
            REPLY,
            "On Mon, 2 Nov 2026 at 10:00, Ivan Testov <ivan@example.test>\nwrote:\n> q",
            id="en-attribution-wrapped",
        ),
        pytest.param(
            f"{REPLY}\n\n{EN_ATTR}\nНужен счёт без угловых скобок\nстрока два",
            REPLY,
            f"{EN_ATTR}\nНужен счёт без угловых скобок\nстрока два",
            id="attribution-without-gt-everything-after",
        ),
        pytest.param(
            f"{REPLY}\n\n-----Original Message-----\nFrom: A\nSent: B\n\nТело",
            REPLY,
            "-----Original Message-----\nFrom: A\nSent: B\n\nТело",
            id="original-message",
        ),
        pytest.param(
            f"{REPLY}\n\n-----Исходное сообщение-----\nОт: A\n\nТело",
            REPLY,
            "-----Исходное сообщение-----\nОт: A\n\nТело",
            id="original-message-ru",
        ),
        pytest.param(
            f"{REPLY}\n\n________________________________\nFrom: A <a@example.test>\n"
            "Sent: Monday\nTo: B\nSubject: Re: x\n\nТело",
            REPLY,
            "________________________________\nFrom: A <a@example.test>\n"
            "Sent: Monday\nTo: B\nSubject: Re: x\n\nТело",
            id="outlook-header-block",
        ),
        pytest.param(
            f"{REPLY}\n\nОт: A <a@example.test>\nОтправлено: Пн\nКому: B\nТема: Re: x\n\nТело",
            REPLY,
            "От: A <a@example.test>\nОтправлено: Пн\nКому: B\nТема: Re: x\n\nТело",
            id="outlook-header-block-ru",
        ),
        pytest.param(
            f"{REPLY}\n> цитата без подписи\n> вторая",
            REPLY,
            "> цитата без подписи\n> вторая",
            id="gt-run-at-end",
        ),
        pytest.param(
            f"{REPLY}\n\n-- \nИван Тестов\nООО «Тест»\n+998 00 000 00 00",
            REPLY,
            "--\nИван Тестов\nООО «Тест»\n+998 00 000 00 00",
            id="signature",
        ),
        pytest.param(
            f"{REPLY}\n\n--\nПодпись",
            REPLY,
            "--\nПодпись",
            id="signature-no-space",
        ),
        pytest.param(
            f"{REPLY}\n\n-- \nПодпись\n\n{EN_ATTR}\n> q",
            REPLY,
            f"--\nПодпись\n\n{EN_ATTR}\n> q",
            id="signature-then-quote",
        ),
        pytest.param(
            f"{EN_ATTR}\n> вопрос\n\n{REPLY}",
            f"{EN_ATTR}\n> вопрос\n\n{REPLY}",
            "",
            id="bottom-posting-not-cut",
        ),
        pytest.param(
            f"> вопрос 1\nОтвет 1\n> вопрос 2\n{REPLY}",
            f"> вопрос 1\nОтвет 1\n> вопрос 2\n{REPLY}",
            "",
            id="inline-replies-not-cut",
        ),
        pytest.param(
            f"{EN_ATTR}\n> только цитата",
            f"{EN_ATTR}\n> только цитата",
            "",
            id="nothing-but-quote-stays",
        ),
        pytest.param(
            "-----Original Message-----\nFrom: A\n\nПереслано целиком",
            "-----Original Message-----\nFrom: A\n\nПереслано целиком",
            "",
            id="nothing-above-original-stays",
        ),
        pytest.param(
            "Сравнение: a -- b и 5 > 3\nвторая строка 2 > 1",
            "Сравнение: a -- b и 5 > 3\nвторая строка 2 > 1",
            "",
            id="dashes-and-gt-inside-lines",
        ),
        pytest.param(
            f"{REPLY}\n\nИван Тестов <ivan@example.test>:\n> q",
            REPLY,
            "Иван Тестов <ivan@example.test>:\n> q",
            id="name-email-colon-attribution",
        ),
        pytest.param(
            f"{REPLY}\n\n2 Nov 2026, 10:00 Ivan Testov yozdi:\n> q",
            REPLY,
            "2 Nov 2026, 10:00 Ivan Testov yozdi:\n> q",
            id="uz-attribution",
        ),
        pytest.param(
            f"{REPLY}\n\nНа 2 ноября написал Иван:\n> q",
            REPLY,
            "На 2 ноября написал Иван:\n> q",
            id="ru-wrote",
        ),
    ],
)
def test_split_quote(raw: str, main: str, tail: str) -> None:
    assert split_quote(normalize_text(raw)) == (main, tail)


def test_split_quote_empty() -> None:
    assert split_quote("") == ("", "")

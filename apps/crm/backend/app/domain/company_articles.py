"""Статьи компании (W18A-P5, B-079): внутренние инструкции «как у нас принято». Чистые функции.

Админ пишет статью в Настройках (Markdown), черновик видят только те, кто правит, опубликованную —
все сотрудники в «Помощи» рядом с продуктовыми статьями. Данные — в CRM (ADR-0015); правила живут
здесь, чтобы их проверяли тесты без БД, запись — `services/company_articles.py`.
"""

from typing import Final, Literal

LANGUAGES: Final = ("ru", "uz", "en")
STATUSES: Final = ("draft", "published")
Language = Literal["ru", "uz", "en"]
Status = Literal["draft", "published"]

TITLE_MAX_LEN: Final = 200
BODY_MAX_LEN: Final = 20000


class ArticleValueError(ValueError):
    """Значение не прошло проверку; `reason` — подкод для `details.reason`, `field` — поле формы."""

    def __init__(self, reason: str, field: str) -> None:
        super().__init__(f"{field}: {reason}")
        self.reason = reason
        self.field = field


def checked_title(text: str) -> str:
    value = " ".join(text.split())
    if not value:
        raise ArticleValueError("article_title_empty", "title")
    if len(value) > TITLE_MAX_LEN:
        raise ArticleValueError("article_title_too_long", "title")
    return value


def checked_body(text: str) -> str:
    value = text.strip()
    if not value:
        raise ArticleValueError("article_body_empty", "body")
    if len(value) > BODY_MAX_LEN:
        raise ArticleValueError("article_body_too_long", "body")
    return value


def checked_language(value: str) -> Language:
    if value not in LANGUAGES:
        raise ArticleValueError("article_language_unknown", "language")
    return value  # type: ignore[return-value]


def checked_status(value: str) -> Status:
    if value not in STATUSES:
        raise ArticleValueError("article_status_unknown", "status")
    return value  # type: ignore[return-value]

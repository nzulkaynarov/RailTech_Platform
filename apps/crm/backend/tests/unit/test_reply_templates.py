"""Шаблоны ответов: подстановки только {name}/{manager}, русский обязателен, лимиты."""

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.reply_templates import ReplyTemplateIn


def body(ru: str = "Здравствуйте, {name}!", uz: str = "", en: str = "", **extra: Any) -> Any:
    return {"title": "Приветствие", "text": {"ru": ru, "uz": uz, "en": en}, **extra}


def test_valid_with_placeholders() -> None:
    tpl = ReplyTemplateIn.model_validate(body(en="Hi {name}, {manager} here"))
    assert tpl.text.en.endswith("here")


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (body(ru="Привет, {client}"), "text.ru"),
        (body(uz="Salom {name"), "text.uz"),
        (body(ru="  "), "text.ru"),
        (body(en="x" * 4001), "text.en"),
        ({**body(), "title": " "}, "title"),
        ({**body(), "title": "x" * 121}, "title"),
        (body(extra_field=1), "extra"),
    ],
)
def test_invalid(payload: Any, message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ReplyTemplateIn.model_validate(payload)

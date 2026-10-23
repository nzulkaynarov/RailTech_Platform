"""Базовые типы настроек: строгая модель и текст на трёх языках (CONVENTIONS.md §11)."""

import string
from typing import Literal, Self

import structlog
from pydantic import BaseModel, ConfigDict, model_validator

Language = Literal["ru", "uz", "en"]
LANGUAGES: tuple[Language, ...] = ("ru", "uz", "en")

logger = structlog.get_logger(__name__)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _KeepMissing(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def placeholders(template: str) -> frozenset[str]:
    """Имена `{подстановок}` шаблона; некорректный шаблон — ValueError."""
    return frozenset(name for _, name, _, _ in string.Formatter().parse(template) if name)


class LocalizedText(StrictModel):
    ru: str
    uz: str
    en: str

    def get(self, language: Language, **params: str) -> str:
        template: str = getattr(self, language)
        if not params:
            return template
        try:
            # Неизвестная подстановка остаётся как есть, а не роняет /start или /request.
            return template.format_map(_KeepMissing(params))
        except (ValueError, IndexError, AttributeError):
            logger.error("localized_text_format_failed", language=language)
            return template


def localized(ru: str, uz: str, en: str) -> LocalizedText:
    return LocalizedText(ru=ru, uz=uz, en=en)


class CheckedTexts(StrictModel):
    """Тексты, которые админ правит в «Настройках»: подстановки — ровно как в тексте по умолчанию.

    Иначе `{manager}` с опечаткой или лишний `{name}` молча ломают сообщение клиенту.
    """

    @model_validator(mode="after")
    def _same_placeholders(self) -> Self:
        for name, field in type(self).model_fields.items():
            default = field.default
            value = getattr(self, name)
            if not isinstance(default, LocalizedText) or not isinstance(value, LocalizedText):
                continue
            expected = placeholders(default.ru)
            for language in LANGUAGES:
                text = getattr(value, language)
                try:
                    found = placeholders(text)
                except ValueError as exc:
                    raise ValueError(f"{name}.{language}: некорректные фигурные скобки") from exc
                if found != expected:
                    want = ", ".join(f"{{{p}}}" for p in sorted(expected)) or "без подстановок"
                    raise ValueError(f"{name}.{language}: подстановки должны быть: {want}")
        return self

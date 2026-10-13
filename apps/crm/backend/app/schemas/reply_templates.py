"""DTO шаблонов быстрых ответов (аудит 2026-10-12 §5)."""

from datetime import datetime
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.settings_base import LANGUAGES, LocalizedText, placeholders

# Подстановки, которые CRM заполняет в карточке лида; остальные фигурные скобки — ошибка.
TEMPLATE_PLACEHOLDERS: Final = frozenset({"name", "manager"})
_TEXT_MAX: Final = 4000


class ReplyTemplateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=120)
    text: LocalizedText

    @model_validator(mode="after")
    def _check_text(self) -> Self:
        if not self.title.strip():
            raise ValueError("title: пустое название")
        for language in LANGUAGES:
            value: str = getattr(self.text, language)
            if len(value) > _TEXT_MAX:
                raise ValueError(f"text.{language}: не длиннее {_TEXT_MAX} символов")
            try:
                found = placeholders(value)
            except ValueError as exc:
                raise ValueError(f"text.{language}: некорректные фигурные скобки") from exc
            unknown = found - TEMPLATE_PLACEHOLDERS
            if unknown:
                raise ValueError(f"text.{language}: допустимы только {{name}} и {{manager}}")
        if not self.text.ru.strip():
            raise ValueError("text.ru: русский текст обязателен")
        return self


class ReplyTemplateOut(ReplyTemplateIn):
    id: int
    updated_at: datetime

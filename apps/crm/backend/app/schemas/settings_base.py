"""Базовые типы настроек: строгая модель и текст на трёх языках (CLAUDE.md §11)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

Language = Literal["ru", "uz", "en"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LocalizedText(StrictModel):
    ru: str
    uz: str
    en: str

    def get(self, language: Language, **params: str) -> str:
        template: str = getattr(self, language)
        return template.format(**params) if params else template


def localized(ru: str, uz: str, en: str) -> LocalizedText:
    return LocalizedText(ru=ru, uz=uz, en=en)

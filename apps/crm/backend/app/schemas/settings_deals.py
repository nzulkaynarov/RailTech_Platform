"""Настройка `deals`: справочник причин отказа и валюта (Q-013, ADR-0019)."""

from typing import Final

from pydantic import Field

from app.schemas.settings_base import StrictModel

_LOST_REASONS: Final = ("Дорого", "Выбрали конкурента", "Нет бюджета", "Не актуально")
_LOST_REASONS_TAIL: Final = ("Не вышли на связь", "Другое")


class DealsSettings(StrictModel):
    """Справочник причин отказа и валюта новых сделок (Q-013, ADR-0019)."""

    lost_reasons: list[str] = Field(
        default_factory=lambda: [*_LOST_REASONS, *_LOST_REASONS_TAIL], min_length=1
    )
    currency: str = Field(default="UZS", pattern="^[A-Z]{3}$")

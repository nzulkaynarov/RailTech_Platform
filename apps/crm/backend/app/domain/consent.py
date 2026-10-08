"""Согласие на обработку данных (SPEC §6.4)."""

from datetime import datetime


def consent_required(
    consent_given_at: datetime | None, consent_version: str | None, current_version: str
) -> bool:
    """Нужно (повторно) запросить согласие: не давалось или версия текста сменилась."""
    return consent_given_at is None or consent_version != current_version

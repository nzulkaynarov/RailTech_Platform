"""Какие лиды видны как лиды: песочница и якорь группы Telegram — служебные (ADR-0032 п. 3).

Якорный лид `source = 'group'` нужен только как хозяин беседы группы: в реестре, входящих,
«С клиентами», счётчиках, воронке и таймерах его нет. Переписка — по `lead_id` из списка групп.
"""

from typing import Final

from sqlalchemy import ColumnElement

from app.domain.sandbox import SANDBOX_SOURCE
from app.models.leads import Lead

GROUP_ANCHOR_SOURCE: Final = "group"


def is_service_anchor() -> ColumnElement[bool]:
    """Лид-якорь беседы группы Telegram."""
    return Lead.source == GROUP_ANCHOR_SOURCE


def listed() -> ColumnElement[bool]:
    """Лид показывается и считается как лид: не песочница и не служебный якорь."""
    return Lead.source.not_in((SANDBOX_SOURCE, GROUP_ANCHOR_SOURCE))

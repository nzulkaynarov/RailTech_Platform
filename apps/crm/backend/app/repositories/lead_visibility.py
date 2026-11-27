"""Какие лиды видны как лиды: песочница и якорь группы Telegram — служебные (ADR-0032 п. 3).

Якорный лид `source = 'group'` нужен только как хозяин беседы группы: в реестре, входящих,
«С клиентами», счётчиках, воронке и таймерах его нет. Переписка — по `lead_id` из списка групп.
"""

from typing import Final

from sqlalchemy import ColumnElement, select

from app.domain.sandbox import SANDBOX_SOURCE
from app.models.clients import Client
from app.models.leads import Lead

GROUP_ANCHOR_SOURCE: Final = "group"


def is_service_anchor() -> ColumnElement[bool]:
    """Лид-якорь беседы группы Telegram."""
    return Lead.source == GROUP_ANCHOR_SOURCE


def listed() -> ColumnElement[bool]:
    """Лид показывается и считается как лид: не песочница и не служебный якорь."""
    return Lead.source.not_in((SANDBOX_SOURCE, GROUP_ANCHOR_SOURCE))


def not_test_client() -> ColumnElement[bool]:
    """ТЕСТ-1: лид не принадлежит тестовой компании (отметка из ERP); лид без клиента проходит."""
    return Lead.client_id.not_in(
        select(Client.id).where(Client.is_test.is_(True))
    ) | Lead.client_id.is_(None)


def working() -> ColumnElement[bool]:
    """Лид в рабочих списках, счётчиках и панелях: показывается как лид и не из тестовой компании.

    Таймеры и доступ к беседе остаются на `listed()`: уведомления по тестовой компании идут
    (проход кабинета), но в управленческие числа она не входит."""
    return listed() & not_test_client()

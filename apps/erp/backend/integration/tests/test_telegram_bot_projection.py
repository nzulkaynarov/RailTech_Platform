"""Имя Telegram-бота из CRM (`crm.bot.changed`): один источник — CRM, у ERP своей настройки нет.

Прод 2026-11-16: бот принимал лидов, а ERP и кабинет имени бота не знали (пустая переменная окружения) — привязка Telegram
в кабинете и вход через бота не работали. Теперь имя приходит событием и хранится проекцией.
"""

import pytest
from integration.services.telegram_bot import apply_bot_changed, bot_username
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


def _snapshot(username: str, at: str) -> dict:
    return {"username": username, "changed_at": at, "actor": {"type": "system"}}


def test_new_name_applies_and_an_older_snapshot_does_not_overwrite():
    assert bot_username() == ""
    assert apply_bot_changed(_snapshot("railtech_demo_bot", "2026-11-16T09:00:00Z")) is True
    assert bot_username() == "railtech_demo_bot"
    assert apply_bot_changed(_snapshot("railtech_old_bot", "2026-11-15T09:00:00Z")) is False, "старый снимок"
    assert apply_bot_changed(_snapshot("railtech_demo_bot", "2026-11-16T10:00:00Z")) is False, "то же имя"
    assert bot_username() == "railtech_demo_bot"


def test_operator_gives_the_cabinet_the_bot_name():
    client = APIClient()
    assert client.get("/api/portal/v1/operator").json()["bot_username"] is None
    apply_bot_changed(_snapshot("railtech_demo_bot", "2026-11-16T09:00:00Z"))
    assert client.get("/api/portal/v1/operator").json()["bot_username"] == "railtech_demo_bot"


def test_the_bus_handler_is_registered():
    import integration.bus_handlers  # noqa: F401
    from rt_bus.handlers import default_registry

    assert default_registry.match("uz.railtech.crm.bot.changed.v1")

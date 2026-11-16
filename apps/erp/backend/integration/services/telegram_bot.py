"""Проекция имени Telegram-бота из CRM (`crm.bot.changed`): `SystemSetting.telegram_bot_username`.

Имя бота знает только CRM — процесс бота получает его у Telegram (`getMe`) при запуске с токеном из «Подключений». ERP
отдельной настройки не держит: ссылка привязки Telegram в кабинете и `GET /api/portal/v1/operator` берут имя отсюда.
Снимок применяется, только если он не старее уже применённого (`telegram_bot_changed_at`): повтор при старте воркера CRM и
обгон доставки не затирают более новое имя.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from django.db import transaction


def apply_bot_changed(data: Mapping[str, Any]) -> bool:
    """Применить снимок; `True` — имя изменилось."""
    from core.models.settings import SystemSetting

    changed_at = datetime.fromisoformat(str(data["changed_at"]).replace("Z", "+00:00"))
    username = str(data.get("username") or "").strip().lstrip("@")[:32]
    with transaction.atomic():
        setting = SystemSetting.load()
        setting = type(setting).objects.select_for_update().get(pk=setting.pk)
        if setting.telegram_bot_changed_at and changed_at < setting.telegram_bot_changed_at:
            return False
        renamed = bool(username) and username != setting.telegram_bot_username
        if renamed:
            setting.telegram_bot_username = username
        setting.telegram_bot_changed_at = changed_at
        setting.save(update_fields=["telegram_bot_username", "telegram_bot_changed_at", "updated_at"])
    return renamed


def bot_username() -> str:
    """Имя бота для ссылок (без @); пусто — CRM ещё не прислала."""
    from core.models.settings import SystemSetting

    return SystemSetting.load().telegram_bot_username.strip()

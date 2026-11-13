"""Проекция профиля компании из CRM (задача «Н3a2», FIX-42): название — `SystemSetting.platform_name`.

Название ведётся в CRM («Настройки · Компания»); ERP подписывает им письма, документы и кабинет. Снимок применяется, только
если он не старее уже применённого (`company_profile_changed_at`): повтор при старте воркера CRM и обгон доставки не
затирают более новую правку. Пустое название не применяется — остаётся прежнее.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from django.db import transaction


def apply_company_profile(data: Mapping[str, Any]) -> bool:
    """Применить снимок; `True` — название изменилось."""
    from core.models.settings import SystemSetting

    changed_at = datetime.fromisoformat(str(data["changed_at"]).replace("Z", "+00:00"))
    name = str(data.get("name") or "").strip()[:200]
    with transaction.atomic():
        setting = SystemSetting.load()
        setting = type(setting).objects.select_for_update().get(pk=setting.pk)
        if setting.company_profile_changed_at and changed_at < setting.company_profile_changed_at:
            return False
        renamed = bool(name) and name != setting.platform_name
        if renamed:
            setting.platform_name = name
        setting.company_profile_changed_at = changed_at
        setting.save(update_fields=["platform_name", "company_profile_changed_at", "updated_at"])
    return renamed

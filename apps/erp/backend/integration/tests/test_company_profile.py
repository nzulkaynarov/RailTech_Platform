"""Профиль компании из CRM (задача «Н3a2», FIX-42): название — в `SystemSetting.platform_name`, кабинету — `/operator`."""

import pytest
from integration.services.company_profile import apply_company_profile
from rest_framework.test import APIClient

from core.models.settings import SystemSetting

pytestmark = pytest.mark.django_db


def _snapshot(name: str, at: str) -> dict:
    return {"name": name, "phone": "", "site": "", "address": "", "changed_at": at, "actor": {"type": "system"}}


def test_snapshot_renames_and_an_older_one_does_not_overwrite():
    assert apply_company_profile(_snapshot("Новая Компания", "2026-11-13T09:00:00Z")) is True
    assert SystemSetting.load().platform_name == "Новая Компания"
    assert (
        apply_company_profile(_snapshot("Старое имя", "2026-11-12T09:00:00Z")) is False
    ), "старый снимок не применяется"
    assert SystemSetting.load().platform_name == "Новая Компания"
    assert apply_company_profile(_snapshot("", "2026-11-14T09:00:00Z")) is False, "пустое название не применяется"
    assert SystemSetting.load().platform_name == "Новая Компания"


def test_operator_name_is_public_and_hidden_until_crm_sends_the_profile():
    client = APIClient()
    assert client.get("/api/portal/v1/operator").json() == {
        "name": None
    }, "до профиля из CRM — не показываем значение окружения"
    apply_company_profile(_snapshot("RailTech", "2026-11-13T09:00:00Z"))
    assert client.get("/api/portal/v1/operator").json() == {"name": "RailTech"}


def test_the_bus_handler_is_registered():
    import integration.bus_handlers  # noqa: F401
    from rt_bus.handlers import default_registry

    assert default_registry.match("uz.railtech.crm.company_profile.changed.v1")

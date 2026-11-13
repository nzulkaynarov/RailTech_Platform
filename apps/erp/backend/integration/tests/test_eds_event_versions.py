"""Задача «Н» (2026-11-13): EDS публикует v2 событий с номером реестра (обозначение — из настроек нумерации);
ERP обрабатывает v1 и v2 одним и тем же кодом."""

import integration.bus_handlers  # noqa: F401 — регистрирует подписки
import pytest
from rt_bus.handlers import default_registry


@pytest.mark.parametrize("name", ["letter.resolved", "letter.rejected", "approval.decided", "document.signed"])
def test_v1_and_v2_go_to_the_same_handler(name):
    v1 = [h.func for h in default_registry.match(f"uz.railtech.eds.{name}.v1")]
    v2 = [h.func for h in default_registry.match(f"uz.railtech.eds.{name}.v2")]
    assert v1 and v1 == v2

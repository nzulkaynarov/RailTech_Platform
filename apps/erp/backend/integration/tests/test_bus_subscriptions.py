"""Подписки шины: боевой файл загружается и валиден, тесты ERP читают свой (B5).

Тесты ERP строятся на подписчиках crm и erp из `fixtures/subscriptions.yaml` (conftest.py задаёт `RT_BUS_SUBSCRIPTIONS`):
строка нового подписчика в боевом `packages/contracts/bus/subscriptions.yaml` не должна менять их ассерты.
"""

import os
from pathlib import Path

from rt_bus.subscriptions import Subscriptions

from conftest import PRODUCTION_SUBSCRIPTIONS_ENV, TEST_SUBSCRIPTIONS


def production_file() -> Path:
    """Боевой файл подписок: путь из окружения образа/CI, иначе рядом с каталогом схем (`RT_BUS_CONTRACTS_DIR`)."""
    if PRODUCTION_SUBSCRIPTIONS_ENV:
        return Path(PRODUCTION_SUBSCRIPTIONS_ENV)
    return Path(os.environ.get("RT_BUS_CONTRACTS_DIR", "/opt/rt/contracts/events")).parent / "bus/subscriptions.yaml"


def test_production_subscriptions_load_and_are_valid():
    subscriptions = Subscriptions.load(production_file())
    names = {s.name for s in subscriptions.subscribers}
    assert {"crm", "erp"} <= names, "боевой список содержит подписчиков сопряжения CRM ↔ ERP"


def test_the_bus_in_tests_reads_the_fixture_not_the_production_list():
    assert os.environ["RT_BUS_SUBSCRIPTIONS"] == str(TEST_SUBSCRIPTIONS)
    subscriptions = Subscriptions.load(TEST_SUBSCRIPTIONS)
    assert [s.name for s in subscriptions.subscribers] == ["crm", "erp"]

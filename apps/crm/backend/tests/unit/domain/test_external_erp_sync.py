"""Строка «Синхронизация с ERP» в центре внешних сервисов (FIX-11, ADR-0024): таблица кейсов."""

import pytest

from app.domain.external_erp_sync import ErpSyncFacts, erp_sync
from app.domain.external_registry import find, registry


@pytest.mark.parametrize(
    ("facts", "status"),
    [
        pytest.param(ErpSyncFacts(True, 0, 0), "ok", id="nobody-has-access-yet"),
        pytest.param(ErpSyncFacts(True, 3, 0), "ok", id="all-synced"),
        pytest.param(ErpSyncFacts(False, 0, 0), "off", id="erp-not-connected"),
        pytest.param(ErpSyncFacts(True, 3, 1, "boom"), "fail", id="one-failed"),
        pytest.param(ErpSyncFacts(False, 2, 2, "erp_not_configured"), "fail", id="not-connected"),
        pytest.param(ErpSyncFacts(True, 0, 1, "boom"), "fail", id="failed-after-revoke"),
    ],
)
def test_status(facts: ErpSyncFacts, status: str) -> None:
    result = erp_sync(facts)
    assert result.key == "erp_sync"
    assert result.status == status


def test_failure_carries_the_error_and_a_hint_for_the_admin() -> None:
    result = erp_sync(ErpSyncFacts(True, 5, 2, "erp_provision_user: erp_unavailable: timeout"))

    assert result.status == "fail"
    assert "2" in result.summary
    assert result.error == "erp_provision_user: erp_unavailable: timeout"
    assert result.hint is not None
    assert "«Подключения» → «ERP»" in result.hint
    assert result.metrics == {"with_access": 5, "failed": 2}


def test_not_connected_hint_tells_to_connect_erp() -> None:
    result = erp_sync(ErpSyncFacts(False, 1, 1, "erp_provision_user: erp_not_configured: x"))
    assert result.hint is not None
    assert "не подключена" in result.hint


@pytest.mark.parametrize("configured", [True, False])
def test_hint_matches_task_behavior_retry_by_schedule_then_regrant(configured: bool) -> None:
    """FIX-11b: подсказка обещает повтор, который есть (`RETRY` задач), и что делать после него."""
    from app.tasks.erp_users import RETRY

    assert (RETRY.max_attempts or 0) > 1
    hint = erp_sync(ErpSyncFacts(configured, 1, 1, "x")).hint
    assert hint is not None
    assert "повторя" in hint
    assert "снова выдайте доступ" in hint


def test_registry_row_points_to_the_erp_connector_and_is_checked_every_minute() -> None:
    spec = find(registry({}), "erp_sync")
    assert spec is not None
    assert spec.source == "crm"
    assert spec.tiers == ("cheap",)
    assert spec.fix_path == "/integrations?tab=erp"
    assert spec.switch is None

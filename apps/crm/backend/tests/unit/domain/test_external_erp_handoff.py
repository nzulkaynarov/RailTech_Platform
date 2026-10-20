"""Строка «Передача клиентов в ERP» центра внешних сервисов (FIX-31, ADR-0024): таблица кейсов."""

import pytest

from app.domain.external_erp_handoff import STUCK_AFTER_MINUTES, ErpHandoffFacts, erp_handoff
from app.domain.external_registry import find, registry


@pytest.mark.parametrize(
    ("facts", "status"),
    [
        pytest.param(ErpHandoffFacts(True, 0, 0, 0), "ok", id="nothing-to-hand-off"),
        pytest.param(ErpHandoffFacts(True, 0, 0, 2), "ok", id="fresh-pending-is-fine"),
        pytest.param(ErpHandoffFacts(False, 0, 0, 0), "off", id="erp-not-connected"),
        pytest.param(ErpHandoffFacts(True, 1, 0, 0, "ООО: erp_inn_conflict"), "fail", id="failed"),
        pytest.param(ErpHandoffFacts(True, 0, 1, 1), "fail", id="stuck"),
        pytest.param(ErpHandoffFacts(False, 1, 0, 0, "x"), "fail", id="failed-erp-disconnected"),
    ],
)
def test_status(facts: ErpHandoffFacts, status: str) -> None:
    result = erp_handoff(facts)
    assert result.key == "erp_handoff"
    assert result.status == status


def test_failure_carries_the_error_and_a_hint_for_the_admin() -> None:
    result = erp_handoff(ErpHandoffFacts(True, 2, 0, 0, "ООО Тест: erp_inn_conflict"))

    assert result.error == "ООО Тест: erp_inn_conflict"
    assert result.hint is not None
    assert "Повторить передачу" in result.hint
    assert result.metrics == {"failed": 2, "stuck": 0, "pending": 0}


def test_stuck_hint_points_to_the_worker() -> None:
    result = erp_handoff(ErpHandoffFacts(True, 0, 3, 3))
    assert result.hint is not None
    assert "воркер" in result.hint


def test_registry_row_is_a_crm_check_without_erp_requests() -> None:
    spec = find(registry({}), "erp_handoff")
    assert spec is not None
    assert (spec.source, spec.tiers, spec.switch) == ("crm", ("cheap",), None)
    assert spec.fix_path == "/clients"
    assert STUCK_AFTER_MINUTES > 5  # дольше обычных повторов задачи (RETRY)

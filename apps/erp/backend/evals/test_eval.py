"""ПЛАТНЫЕ evals ERP: golden-кейсы разбора запроса и сопоставления через настоящий шлюз.

Запуск — только `make -C apps/erp eval-quick CONFIRM=yes` (или `eval`), с согласия владельца на
конкретный прогон (ADR-0005, HANDOFF §4). Без `EVAL_CONFIRM=yes` модуль пропускается целиком —
обычный `pytest` его не трогает. Потолок расходов — `EVAL_MAX_USD` (по умолчанию $0.20): дошли —
оставшиеся кейсы пропускаются.
"""

import os

import pytest
from evals import runner
from evals.cases import load_intake_cases, load_match_cases

pytestmark = [
    pytest.mark.eval,
    pytest.mark.skipif(os.environ.get("EVAL_CONFIRM") != "yes", reason="платный прогон: make eval-quick CONFIRM=yes"),
]


@pytest.fixture(autouse=True)
def _real_gateway(monkeypatch, settings):
    """Снять блокировку транспорта из корневого conftest: здесь — настоящий шлюз стенда."""
    from ai.services import gateway

    monkeypatch.setattr(gateway, "_transport", gateway.http_transport)
    if not settings.AI_IMPORT_ENABLED:
        pytest.skip("ИИ выключен: нужен LITELLM_BASE_URL и ключ ERP")


def _guard():
    if not runner.budget_left():
        pytest.skip(f"потолок расходов evals ${runner.MAX_USD} исчерпан (потрачено ${runner.spent()})")


@pytest.mark.django_db
@pytest.mark.parametrize("case", runner.selected(load_intake_cases()), ids=lambda case: case.id)
def test_intake_case(case):
    _guard()
    score = runner.run_intake_case(case)
    assert score.passed, list(score.failures)


@pytest.mark.django_db
@pytest.mark.parametrize("case", runner.selected(load_match_cases()), ids=lambda case: case.id)
def test_match_case(case):
    _guard()
    score = runner.run_match_case(case)
    assert score.passed, list(score.failures)

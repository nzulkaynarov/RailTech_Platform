"""AI #7 pre-flight заявка quality check — disabled→[], Rule-1 index drop, flag surfaces.

The LiteLLM gateway is faked (ai.testing.FakeGateway) (no paid/nondeterministic calls); we assert the deterministic
contract: gated on AI_IMPORT_ENABLED, out-of-range line_index dropped, a flagged line surfaces.
"""

import pytest
from ai.testing import install_fake_gateway


def _stub_response(findings):
    return {"findings": findings}


@pytest.mark.django_db
def test_preflight_disabled_returns_empty(settings):
    settings.AI_IMPORT_ENABLED = False
    from sourcing.services_ai_preflight import pre_flight_check

    assert pre_flight_check([{"name": "труба", "quantity": 1}]) == []


@pytest.mark.django_db
def test_preflight_drops_out_of_range_index(settings, monkeypatch):
    """Rule 1: a line_index the model returns that is NOT a given line is dropped."""
    settings.AI_IMPORT_ENABLED = True
    # Two findings: index 0 is valid (one input line), index 5 is hallucinated → only 0 survives.
    fake = _stub_response(
        [
            {"line_index": 0, "severity": "warning", "issue": "Расплывчато", "suggestion": "Уточните размер"},
            {"line_index": 5, "severity": "warning", "issue": "invented", "suggestion": "ghost"},
        ]
    )
    install_fake_gateway(monkeypatch).reply_json(fake)
    from sourcing.services_ai_preflight import pre_flight_check

    findings = pre_flight_check([{"name": "труба", "quantity": 1, "unit": "шт"}])
    indices = [finding["line_index"] for finding in findings]
    assert indices == [0]
    assert findings[0]["issue"] == "Расплывчато"
    assert findings[0]["severity"] == "warning"


@pytest.mark.django_db
def test_preflight_flagged_line_surfaces(settings, monkeypatch):
    settings.AI_IMPORT_ENABLED = True
    fake = _stub_response(
        [{"line_index": 1, "severity": "info", "issue": "Нет единицы", "suggestion": "Добавьте ед. изм."}]
    )
    install_fake_gateway(monkeypatch).reply_json(fake)
    from sourcing.services_ai_preflight import pre_flight_check

    findings = pre_flight_check(
        [
            {"name": "Автосцепка СА-3", "quantity": 2, "unit": "шт"},
            {"name": "Болт М12", "quantity": 100},
        ]
    )
    assert len(findings) == 1
    assert findings[0]["line_index"] == 1
    assert findings[0]["severity"] == "info"
    assert findings[0]["suggestion"] == "Добавьте ед. изм."

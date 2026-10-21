"""Схема golden-кейсов: все YAML валидны, id уникальны, покрытие категорий Фазы 2."""

from collections import Counter

from evals.golden import load_cases


def test_golden_cases_are_valid_and_unique() -> None:
    cases = load_cases()
    assert len(cases) >= 40
    counts = Counter(c.id for c in cases)
    assert [i for i, n in counts.items() if n > 1] == []


def test_phase2_categories_and_languages_are_covered() -> None:
    cases = load_cases()
    categories = {c.category for c in cases}
    assert {"kb_answer", "not_in_kb", "injection", "smalltalk"} <= categories
    kb_languages = {c.language for c in cases if c.category == "kb_answer"}
    assert kb_languages == {"ru", "uz", "en"}


def test_qualifier_cases_are_valid() -> None:
    from evals.qualifier_cases import load_qualifier_cases

    cases = load_qualifier_cases()
    assert len(cases) >= 30
    assert len({c.id for c in cases}) == len(cases)
    assert sum(c.expect.escalate for c in cases) >= 10


def test_customer_cases_present() -> None:
    cases = [c for c in load_cases() if c.mode == "customer"]
    assert len(cases) >= 10
    assert {"deliver_document", "handoff", "answer"} <= {a for c in cases for a in c.expect.actions}


SERVICE_CASES = [c for c in load_cases() if c.category == "service_mode"]
# Обязательные сценарии M3-CRM-07: где счёт, когда поставка, пришлите договор, цена (клиент и лид),
# ERP недоступен, чужие данные не просить.
REQUIRED_SERVICE_CASES = {
    "service-invoice-where-ru",
    "service-delivery-when-ru",
    "service-contract-send-ru",
    "service-contract-missing-ru",
    "service-price-customer-ru",
    "service-price-lead-ru",
    "service-erp-down-ru",
    "service-foreign-data-ru",
}


def test_service_mode_cases_cover_the_required_scenarios() -> None:
    assert {c.id for c in SERVICE_CASES} >= REQUIRED_SERVICE_CASES
    assert {c.language for c in SERVICE_CASES} == {"ru", "uz", "en"}


def test_service_cases_use_only_tools_the_model_is_given() -> None:
    from app.agents.dialog.erp_tools import ERP_TOOL_NAMES

    for case in SERVICE_CASES:
        expected = set(case.expect.erp_tools_any)
        fixture = set(case.erp.tools) if case.erp else set()
        assert expected <= ERP_TOOL_NAMES, case.id
        assert fixture <= ERP_TOOL_NAMES, case.id
        assert case.erp is None or case.mode == "customer", f"{case.id}: ERP только клиенту"


def test_price_is_for_customers_only() -> None:
    by_id = {c.id: c for c in SERVICE_CASES}
    customer, lead = by_id["service-price-customer-ru"], by_id["service-price-lead-ru"]
    assert customer.mode == "customer"
    assert customer.erp is not None
    assert customer.erp.tools["search_catalog"][0]["price"]["amount"]
    assert lead.mode == "prospect"
    assert lead.erp is None
    assert lead.expect.no_erp_calls
    assert set(lead.expect.must_not_include) >= {"сум", "usd"}


def test_erp_down_case_expects_an_honest_handover() -> None:
    case = {c.id: c for c in SERVICE_CASES}["service-erp-down-ru"]
    assert case.erp is not None
    assert case.erp.available is False
    assert "create_service_request" in case.expect.tool_calls_any
    assert case.expect.erp_tools_any

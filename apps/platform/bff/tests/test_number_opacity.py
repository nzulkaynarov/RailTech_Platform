"""СЦ-5: номер непрозрачен — вид и текущее значение берутся из ERP, не из префикса."""

from app.deal_number_live import number_of
from app.schemas_erp_stock import request_ref


def test_number_of_prefers_the_live_erp_number_over_the_stored_copy() -> None:
    assert number_of({"number": "PRJ-2026-104"}, "ЗВ-2026-104") == "PRJ-2026-104"


def test_number_of_falls_back_to_the_stored_copy() -> None:
    assert number_of(None, "ЗВ-2026-104") == "ЗВ-2026-104"
    assert number_of({"number": ""}, "ЗВ-2026-104") == "ЗВ-2026-104"
    assert number_of({}, None) is None


def test_request_kind_follows_the_stage_not_the_prefix() -> None:
    cyrillic_prefix_request = request_ref({"number": "ПР-2026-001", "stage_code": "CALCULATING"})
    latin_project = request_ref({"number": "RQ-2026-002", "stage_code": "CONTRACT_SIGNED"})
    assert cyrillic_prefix_request is not None
    assert latin_project is not None
    assert cyrillic_prefix_request.path.startswith("/erp/calc/")
    assert latin_project.path == "/eds/projects/RQ-2026-002"

"""Сервисы ERP в центре внешних сервисов (M3-ERP-06): `Health.externals[]` → результат проверки."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain import external_erp_reported as rules
from app.domain.system_status import ErpExternal, ErpFacts

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
SECRET_FREE_ERROR = "ConnectionError: Could not connect to the endpoint URL: http://minio:9000"


def item(code: str = "cbu_rates", status: str = "ok", **kw: object) -> ErpExternal:
    base: dict[str, object] = {
        "code": code,
        "status": status,
        "enabled": True,
        "switchable": True,
        "last_success_at": NOW - timedelta(hours=1),
        "last_error_at": None,
        "last_error": None,
        "ok_24h": 3,
        "errors_24h": 0,
    }
    return ErpExternal(**{**base, **kw})  # type: ignore[arg-type]


def facts(*externals: ErpExternal, **kw: object) -> ErpFacts:
    return ErpFacts(configured=True, status="ok", externals=externals, **kw)  # type: ignore[arg-type]


def test_ok_service_carries_counters_and_marks() -> None:
    result = rules.erp_external("erp.cbu_rates", facts(item()))
    assert result.status == "ok"
    assert result.metrics["ok_24h"] == 3
    assert result.metrics["errors_24h"] == 0
    assert result.metrics["last_success_at"] == (NOW - timedelta(hours=1)).isoformat()
    assert result.metrics["last_error_at"] is None
    assert result.hint is None
    assert result.error is None


@pytest.mark.parametrize(
    ("erp_status", "expected"),
    [
        ("ok", "ok"),
        ("degraded", "warn"),
        ("fail", "fail"),
        ("unknown", "unknown"),
        ("disabled", "off"),
    ],
)
def test_status_mapping(erp_status: str, expected: str) -> None:
    errored = erp_status in ("degraded", "fail")
    row = item(
        status=erp_status,
        last_error_at=NOW if errored else None,
        last_error="TimeoutError: slow" if errored else None,
    )
    assert rules.erp_external("erp.cbu_rates", facts(row)).status == expected


@pytest.mark.parametrize("code", ["cbu_rates", "customs_tariff", "mail", "litellm", "s3"])
def test_failure_has_what_happened_the_error_and_what_to_do(code: str) -> None:
    row = item(
        code,
        "fail",
        last_success_at=None,
        last_error_at=NOW,
        last_error=SECRET_FREE_ERROR,
        ok_24h=0,
        errors_24h=4,
    )
    result = rules.erp_external(f"erp.{code}", facts(row))
    assert result.status == "fail"
    assert result.error == SECRET_FREE_ERROR
    assert result.hint
    assert len(result.summary) > 20
    assert result.metrics["errors_24h"] == 4


def test_degraded_after_a_fresh_error_and_degraded_when_stale_read_differently() -> None:
    fresh = item(status="degraded", last_error_at=NOW, last_error="TimeoutError: slow")
    stale = item(status="degraded", last_success_at=NOW - timedelta(days=5), ok_24h=0)
    assert "не удалась" in rules.erp_external("erp.cbu_rates", facts(fresh)).summary
    assert "Давно не было" in rules.erp_external("erp.cbu_rates", facts(stale)).summary


def test_disabled_from_crm_differs_from_not_configured() -> None:
    off = rules.erp_external("erp.mail", facts(item("mail", "disabled", enabled=False)))
    unconfigured = rules.erp_external("erp.mail", facts(item("mail", "disabled", enabled=True)))
    assert (off.status, unconfigured.status) == ("off", "off")
    assert "Выключен из CRM" in off.summary
    assert off.hint is None
    assert "не настроен" in unconfigured.summary
    assert unconfigured.hint


def test_unknown_service_status_has_no_data_text() -> None:
    result = rules.erp_external(
        "erp.s3", facts(item("s3", "unknown", last_success_at=None, ok_24h=0))
    )
    assert result.status == "unknown"
    assert "пока нет" in result.summary


def test_erp_not_configured_is_off_not_a_failure() -> None:
    result = rules.erp_external("erp.mail", ErpFacts(configured=False))
    assert result.status == "off"
    assert "Подключения" in (result.hint or "")


def test_unreachable_erp_is_unknown_so_six_services_do_not_open_six_incidents() -> None:
    result = rules.erp_external("erp.mail", ErpFacts(configured=True, error="unavailable"))
    assert result.status == "unknown"
    assert result.error == "unavailable"
    assert "Проверить связь" in (result.hint or "")


def test_old_erp_without_the_field_is_no_data_with_an_upgrade_hint() -> None:
    result = rules.erp_external("erp.mail", ErpFacts(configured=True, status="ok", externals=None))
    assert result.status == "unknown"
    assert "не передаёт" in result.summary
    assert "M3-ERP-06" in (result.hint or "")


def test_service_missing_from_the_list_and_unknown_codes_are_tolerated() -> None:
    other = item("brand_new_service")
    result = rules.erp_external("erp.mail", facts(other))
    assert result.status == "unknown"
    assert "не передала" in result.summary
    odd = rules.erp_external("erp.brand_new_service", facts(other))
    assert odd.status == "ok"


def test_unknown_status_value_from_a_newer_erp_reads_as_unknown() -> None:
    assert rules.erp_external("erp.mail", facts(item("mail", "on_fire"))).status == "unknown"

"""`Health.externals[]` в ответе ERP (M3-ERP-06): терпимый читатель и выключатель сервиса ERP."""

import json
from typing import Any

import httpx
import pytest
import respx

from app.config import Settings
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError
from app.integrations.erp import ErpConnection, HttpxErpProbe
from app.integrations.erp_externals import HttpxErpSwitchClient
from app.security.secrets_store import SecretsStore

BASE = "https://erp.internal"
HEALTH = f"{BASE}/api/integration/v1/health"
SWITCH = f"{BASE}/api/integration/v1/externals/mail/switch"
CONNECTION = ErpConnection(base_url=BASE, token="test-token")

SERVICE = {
    "code": "mail",
    "status": "degraded",
    "enabled": True,
    "switchable": True,
    "last_success_at": "2026-10-21T10:00:00+00:00",
    "last_error_at": "2026-10-21T11:00:00+00:00",
    "last_error": "SMTPServerDisconnected: connection unexpectedly closed",
    "ok_24h": 7,
    "errors_24h": 2,
}


def health(**extra: Any) -> dict[str, Any]:
    return {
        "status": "ok",
        "version": "0.3.0",
        "migrations_applied": True,
        "queue_alive": True,
        "checked_at": "2026-10-21T12:00:00+00:00",
        **extra,
    }


async def probe(body: dict[str, Any]) -> Any:
    with respx.mock() as mock:
        mock.get(HEALTH).respond(200, json=body)
        return await HttpxErpProbe().health(CONNECTION)


async def test_externals_are_parsed() -> None:
    result = await probe(health(externals=[SERVICE]))
    assert result.externals is not None
    (mail,) = result.externals
    assert (mail.code, mail.status, mail.enabled, mail.switchable) == (
        "mail",
        "degraded",
        True,
        True,
    )
    assert (mail.ok_24h, mail.errors_24h) == (7, 2)
    assert mail.last_error == "SMTPServerDisconnected: connection unexpectedly closed"
    assert mail.last_success_at is not None
    assert mail.last_error_at is not None


async def test_erp_before_m3_erp_06_has_no_field() -> None:
    assert (await probe(health())).externals is None


@pytest.mark.parametrize("junk", [None, {}, "mail", 5])
async def test_a_field_of_the_wrong_shape_is_no_data_not_a_broken_health(junk: Any) -> None:
    result = await probe(health(externals=junk))
    assert result.externals is None
    assert result.status == "ok"


async def test_broken_records_are_dropped_unknown_values_are_tolerated() -> None:
    body = health(
        externals=[
            SERVICE,
            {"status": "ok"},  # нет code
            "garbage",
            {**SERVICE, "code": "future_service", "status": "melting", "new_field": {"a": 1}},
            {**SERVICE, "code": "s3", "last_error": "x" * 500, "ok_24h": -4},
        ]
    )
    result = await probe(body)
    assert result.externals is not None
    assert [e.code for e in result.externals] == ["mail", "future_service", "s3"]
    future, s3 = result.externals[1], result.externals[2]
    assert future.status == "unknown", "статус из будущего читается как «нет данных»"
    assert len(s3.last_error or "") == 200
    assert s3.ok_24h == 0


# ── Выключатель ──────────────────────────────────────────────────────────────────────


class _Store(SecretsStore):
    def __init__(self) -> None:
        super().__init__(None, None)  # type: ignore[arg-type]

    @property
    def enabled(self) -> bool:
        return False


def switch_client() -> HttpxErpSwitchClient:
    return HttpxErpSwitchClient(
        _Store(), Settings(erp_base_url=BASE, erp_service_token="test-token")
    )


async def test_switch_off_sends_the_contract_body_with_the_token() -> None:
    with respx.mock() as mock:
        route = mock.put(SWITCH).respond(
            200, json={"code": "mail", "enabled": False, "changed_at": "2026-10-21T12:00:00Z"}
        )
        await switch_client().set_switch("mail", enabled=False, reason="утечка ключа")
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-token"
    assert json.loads(request.content) == {"enabled": False, "reason": "утечка ключа"}


async def test_switch_on_sends_no_reason() -> None:
    with respx.mock() as mock:
        route = mock.put(SWITCH).respond(
            200, json={"code": "mail", "enabled": True, "changed_at": "2026-10-21T12:00:00Z"}
        )
        await switch_client().set_switch("mail", enabled=True, reason="не нужна")
    assert json.loads(route.calls.last.request.content) == {"enabled": True}


@pytest.mark.parametrize(
    ("status", "detail"),
    [(404, "NOT_FOUND"), (409, "NOT_SWITCHABLE")],
)
async def test_switch_refused_by_erp_is_a_conflict(status: int, detail: str) -> None:
    with respx.mock() as mock:
        mock.put(SWITCH).respond(status, json={"detail": detail})
        with pytest.raises(ConflictError) as exc_info:
            await switch_client().set_switch("mail", enabled=False, reason=None)
    assert exc_info.value.details["reason"] == Reason.SERVICE_NOT_SWITCHABLE


async def test_switch_erp_down_and_unauthorized_are_upstream_errors() -> None:
    with respx.mock() as mock:
        mock.put(SWITCH).mock(side_effect=httpx.ConnectError("refused"))
        with pytest.raises(UpstreamUnavailableError) as down:
            await switch_client().set_switch("mail", enabled=False, reason=None)
        assert down.value.details["reason"] == Reason.ERP_UNAVAILABLE
    with respx.mock() as mock:
        mock.put(SWITCH).respond(401, json={"detail": "UNAUTHORIZED"})
        with pytest.raises(UpstreamUnavailableError) as denied:
            await switch_client().set_switch("mail", enabled=False, reason=None)
        assert denied.value.details["reason"] == Reason.ERP_UNAUTHORIZED
    with respx.mock() as mock:
        mock.put(SWITCH).respond(503, json={"detail": "x"})
        with pytest.raises(UpstreamUnavailableError):
            await switch_client().set_switch("mail", enabled=False, reason=None)

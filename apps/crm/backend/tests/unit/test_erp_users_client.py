"""Клиент ERP для сотрудников (FIX-11): провижининг и отзыв сессий, коды ответов и ошибки."""

import httpx
import pytest
import respx

from app.config import Settings
from app.domain.errors import ConflictError, Reason, UpstreamUnavailableError, ValidationFailedError
from app.integrations.erp_users import HttpxErpUsersClient, ProvisionPayload
from app.security.secrets_store import SecretsStore

BASE = "https://erp.internal"
PROVISION = f"{BASE}/api/integration/v1/users/provision"
REVOKE = f"{BASE}/api/integration/v1/users/42/sessions"


class _Store(SecretsStore):
    def __init__(self) -> None:
        super().__init__(None, None)  # type: ignore[arg-type]

    @property
    def enabled(self) -> bool:
        return False


def _client(base_url: str = BASE) -> HttpxErpUsersClient:
    config = Settings(erp_base_url=base_url, erp_service_token="test-token")
    return HttpxErpUsersClient(_Store(), config)


PAYLOAD = ProvisionPayload(
    crm_user_id=42,
    email="manager@railtech.uz",
    name="Менеджер",
    role="backoffice",
    permissions=("deal.manage", "quote.build"),
)


@pytest.mark.asyncio
async def test_provision_sends_token_and_idempotency_key() -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(PROVISION).respond(201, json={"erp_user_id": 7, "crm_user_id": 42})
        erp_user_id = await _client().provision_user(PAYLOAD)

    assert erp_user_id == 7
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["Idempotency-Key"]


@pytest.mark.asyncio
async def test_provision_body_matches_contract_fields() -> None:
    import json

    with respx.mock() as mock:
        route = mock.post(PROVISION).respond(200, json={"erp_user_id": 7, "crm_user_id": 42})
        await _client().provision_user(PAYLOAD)
    body = json.loads(route.calls.last.request.content)
    assert body == {
        "crm_user_id": 42,
        "email": "manager@railtech.uz",
        "name": "Менеджер",
        "role": "backoffice",
        "permissions": ["deal.manage", "quote.build"],
        "is_active": True,
    }


@pytest.mark.asyncio
async def test_provision_email_conflict_is_a_permanent_conflict() -> None:
    with respx.mock() as mock:
        mock.post(PROVISION).respond(409, json={"detail": "EMAIL_CONFLICT"})
        with pytest.raises(ConflictError) as exc_info:
            await _client().provision_user(PAYLOAD)
    assert exc_info.value.details["reason"] == Reason.ERP_EMAIL_CONFLICT


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 422])
async def test_provision_validation_error_is_permanent(status: int) -> None:
    with respx.mock() as mock:
        mock.post(PROVISION).respond(status, json={"detail": "VALIDATION_ERROR"})
        with pytest.raises(ValidationFailedError):
            await _client().provision_user(PAYLOAD)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "reason"), [(401, "erp_unauthorized"), (403, "erp_unauthorized")]
)
async def test_wrong_service_token_is_reported_as_unauthorized(status: int, reason: str) -> None:
    with respx.mock() as mock:
        mock.post(PROVISION).respond(status)
        mock.delete(REVOKE).respond(status)
        with pytest.raises(UpstreamUnavailableError) as provision_exc:
            await _client().provision_user(PAYLOAD)
        with pytest.raises(UpstreamUnavailableError) as revoke_exc:
            await _client().revoke_sessions(42)
    assert provision_exc.value.details["reason"] == reason
    assert revoke_exc.value.details["reason"] == reason


@pytest.mark.asyncio
async def test_provision_server_error_is_transient() -> None:
    with respx.mock() as mock:
        mock.post(PROVISION).respond(502)
        with pytest.raises(UpstreamUnavailableError) as exc_info:
            await _client().provision_user(PAYLOAD)
    assert exc_info.value.details["reason"] == Reason.ERP_BAD_RESPONSE


@pytest.mark.asyncio
async def test_provision_bad_json_is_transient() -> None:
    with respx.mock() as mock:
        mock.post(PROVISION).respond(201, json={"unexpected": 1})
        with pytest.raises(UpstreamUnavailableError):
            await _client().provision_user(PAYLOAD)


@pytest.mark.asyncio
async def test_timeout_and_network_errors_are_transient() -> None:
    with respx.mock() as mock:
        mock.post(PROVISION).mock(side_effect=httpx.ConnectTimeout("slow"))
        mock.delete(REVOKE).mock(side_effect=httpx.ConnectError("down"))
        with pytest.raises(UpstreamUnavailableError) as timeout_exc:
            await _client().provision_user(PAYLOAD)
        with pytest.raises(UpstreamUnavailableError) as network_exc:
            await _client().revoke_sessions(42)
    assert timeout_exc.value.details["reason"] == Reason.ERP_UNAVAILABLE
    assert network_exc.value.details["reason"] == Reason.ERP_UNAVAILABLE


@pytest.mark.asyncio
async def test_revoke_sends_delete_with_token() -> None:
    with respx.mock(assert_all_called=True) as mock:
        route = mock.delete(REVOKE).respond(204)
        assert await _client().revoke_sessions(42) is True
    assert route.calls.last.request.headers["Authorization"] == "Bearer test-token"


@pytest.mark.asyncio
async def test_revoke_of_user_unknown_to_erp_is_not_an_error() -> None:
    with respx.mock() as mock:
        mock.delete(REVOKE).respond(404, json={"detail": "NOT_FOUND"})
        assert await _client().revoke_sessions(42) is False


@pytest.mark.asyncio
async def test_revoke_unexpected_status_is_transient() -> None:
    with respx.mock() as mock:
        mock.delete(REVOKE).respond(500)
        with pytest.raises(UpstreamUnavailableError):
            await _client().revoke_sessions(42)


@pytest.mark.asyncio
async def test_not_configured_connector_is_a_permanent_conflict() -> None:
    client = HttpxErpUsersClient(_Store(), Settings(erp_base_url="", erp_service_token=""))
    for call in (client.provision_user(PAYLOAD), client.revoke_sessions(42)):
        with pytest.raises(ConflictError) as exc_info:
            await call
        assert exc_info.value.details["reason"] == Reason.ERP_NOT_CONFIGURED


@pytest.mark.asyncio
async def test_invalid_base_url_is_rejected_before_any_request() -> None:
    with respx.mock(assert_all_called=False) as mock:
        route = mock.route()
        with pytest.raises(ValidationFailedError):
            await _client(base_url="ftp://erp.internal").revoke_sessions(42)
    assert not route.called

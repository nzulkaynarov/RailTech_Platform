"""Unit-тесты клиента передачи в бэк-офис (M3-CRM-03, ADR-0022).

POST /api/integration/v1/clients/handoff: контракты, идемпотентность, обработка кодов и ошибок.
"""

import httpx
import pytest
import respx

from app.config import Settings
from app.domain.errors import (
    ConflictError,
    Reason,
    UpstreamUnavailableError,
    ValidationFailedError,
)
from app.integrations.erp import (
    HandoffCompanyPayload,
    HandoffConsentPayload,
    HandoffContactPayload,
    HandoffInvitePayload,
    HandoffNeedPayload,
    HandoffOwnerPayload,
    HandoffPayload,
    HttpxErpClient,
    handoff_payload_to_dict,
)
from app.security.secrets_store import SecretsStore


class _DummyStore(SecretsStore):
    def __init__(self, token: str | None = None) -> None:
        super().__init__(None, None)  # type: ignore[arg-type]
        self._token = token

    @property
    def enabled(self) -> bool:
        return True

    async def get(self, key: str) -> str | None:
        return self._token


def _sample_payload() -> HandoffPayload:
    return HandoffPayload(
        crm_client_id=101,
        crm_lead_id=501,
        company=HandoffCompanyPayload(
            name="ООO Тест", inn="1234567890", segment="smb", language="ru"
        ),
        contacts=[
            HandoffContactPayload(
                crm_contact_id=201,
                name="Иван Иванов",
                phone="+998901234567",
                email="ivan@example.com",
                telegram_user_id=987654321,
                language="ru",
                is_primary=True,
                preferred_channel="both",
            )
        ],
        need=HandoffNeedPayload(
            summary="Потребность в колесных парах",
            product_interest=["wheelsets"],
        ),
        owner=HandoffOwnerPayload(crm_user_id=1, name="Менеджер Тестов"),
        consent=HandoffConsentPayload(given_at="2026-10-16T12:00:00Z", version="1.0"),
        create_request=True,
        invite=HandoffInvitePayload(channels=["telegram", "email"]),
    )


def test_handoff_payload_to_dict_matches_contract():
    payload = _sample_payload()
    data = handoff_payload_to_dict(payload)

    assert data["crm_client_id"] == 101
    assert data["crm_lead_id"] == 501
    assert data["company"]["name"] == "ООO Тест"
    assert data["company"]["inn"] == "1234567890"
    assert len(data["contacts"]) == 1
    assert data["contacts"][0]["crm_contact_id"] == 201
    assert data["contacts"][0]["preferred_channel"] == "both"
    assert data["need"]["summary"] == "Потребность в колесных парах"
    assert data["owner"]["crm_user_id"] == 1
    assert data["consent"]["version"] == "1.0"
    assert data["create_request"] is True
    assert data["invite"]["channels"] == ["telegram", "email"]


@pytest.mark.asyncio
async def test_handoff_client_success():
    config = Settings(erp_base_url="https://erp.internal", erp_service_token="test-token")  # type: ignore[call-arg]
    client = HttpxErpClient(_DummyStore("test-token"), config)
    payload = _sample_payload()

    with respx.mock(assert_all_called=True) as respx_mock:
        route = respx_mock.post("https://erp.internal/api/integration/v1/clients/handoff").respond(
            201,
            json={
                "erp_company_id": 42,
                "erp_request_id": 84,
                "invite": {
                    "sent_via": ["telegram", "email"],
                    "cabinet_url": "https://cabinet.internal/auth/magic/abc",
                },
            },
        )
        res = await client.handoff_client(payload, idempotency_key="fixed-uuid-1234")

        assert res.erp_company_id == 42
        assert res.erp_request_id == 84
        assert res.invite_sent_via == ["telegram", "email"]
        assert res.cabinet_url == "https://cabinet.internal/auth/magic/abc"
        assert route.called
        req = route.calls.last.request
        assert req.headers["Authorization"] == "Bearer test-token"
        assert req.headers["Idempotency-Key"] == "fixed-uuid-1234"


@pytest.mark.asyncio
async def test_handoff_client_unconfigured():
    config = Settings(erp_base_url="", erp_service_token="")  # type: ignore[call-arg]
    client = HttpxErpClient(_DummyStore(None), config)
    payload = _sample_payload()

    with pytest.raises(ConflictError) as exc_info:
        await client.handoff_client(payload)
    assert exc_info.value.details["reason"] == Reason.ERP_NOT_CONFIGURED.value


@pytest.mark.asyncio
async def test_handoff_client_unauthorized():
    config = Settings(erp_base_url="https://erp.internal", erp_service_token="bad-token")  # type: ignore[call-arg]
    client = HttpxErpClient(_DummyStore("bad-token"), config)
    payload = _sample_payload()

    with respx.mock:
        respx.post("https://erp.internal/api/integration/v1/clients/handoff").respond(401)
        with pytest.raises(UpstreamUnavailableError) as exc_info:
            await client.handoff_client(payload)
        assert exc_info.value.details["reason"] == Reason.ERP_UNAUTHORIZED.value


@pytest.mark.asyncio
async def test_handoff_client_validation_error():
    config = Settings(erp_base_url="https://erp.internal", erp_service_token="test-token")  # type: ignore[call-arg]
    client = HttpxErpClient(_DummyStore("test-token"), config)
    payload = _sample_payload()

    with respx.mock:
        respx.post("https://erp.internal/api/integration/v1/clients/handoff").respond(
            422, text="Field missing"
        )
        with pytest.raises(ValidationFailedError) as exc_info:
            await client.handoff_client(payload)
        assert exc_info.value.details["reason"] == Reason.ERP_BAD_RESPONSE.value


@pytest.mark.asyncio
async def test_handoff_client_timeout():
    config = Settings(erp_base_url="https://erp.internal", erp_service_token="test-token")  # type: ignore[call-arg]
    client = HttpxErpClient(_DummyStore("test-token"), config)
    payload = _sample_payload()

    with respx.mock:
        respx.post("https://erp.internal/api/integration/v1/clients/handoff").mock(
            side_effect=httpx.TimeoutException("timeout")
        )
        with pytest.raises(UpstreamUnavailableError) as exc_info:
            await client.handoff_client(payload)
        assert exc_info.value.details["reason"] == Reason.ERP_UNAVAILABLE.value

"""Тесты сервиса и обработчика коммерческой подписи (SIGN-4, ADR-0024):
`uz.railtech.erp.signing.requested.v1` -> `uz.railtech.eds.signing.decided.v1`.
"""

from typing import Any

import httpx
import pytest

from app.container import Container
from tests.domain import Person, deliver_erp, outbox
from tests.helpers import example

pytestmark = pytest.mark.pg

URL_AUTHORITIES = "/api/v1/signing/authorities"


def signing_requested(
    *,
    kind: str = "quote",
    object_id: int = 101,
    number: str = "КП-2026/042",
    amount_tiyins: int = 50_000_000_00,  # 50,000,000 UZS
    currency: str = "UZS",
    title: str = "Поставка вагонов",
    signer_crm_user_id: int = 3,
    signer_name: str = "Рустам Директоров",
) -> dict[str, Any]:
    envelope = example("erp/signing.requested.v1")
    envelope["data"]["object"].update(
        kind=kind,
        object_id=object_id,
        number=number,
        amount_tiyins=amount_tiyins,
        currency=currency,
        title=title,
    )
    envelope["data"]["requested_signer"] = {
        "crm_user_id": signer_crm_user_id,
        "name": signer_name,
        "position": "Руководитель",
    }
    return envelope


async def test_commercial_signing_approved_for_director(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    # 1. Выдаем директору полномочие по уставу на все коммерческие документы
    auth_resp = await client.post(
        URL_AUTHORITIES,
        json={
            "crm_user_id": staff["director"].id,
            "kinds": ["quote", "contract", "invoice", "act"],
            "basis": "charter",
            "valid_from": "2026-01-01",
        },
        headers=staff["admin"].headers,
    )
    assert auth_resp.status_code == 201, auth_resp.text

    # 2. Доставляем событие от ERP
    envelope = signing_requested(
        kind="quote",
        object_id=42,
        number="КП-2026/042",
        amount_tiyins=150_000_000_00,  # 150M UZS
        signer_crm_user_id=staff["director"].id,
        signer_name=staff["director"].name,
    )
    status = await deliver_erp(client, container, envelope)
    assert status == "processed"

    # 3. Проверяем outbox: событие signing.decided
    events = await outbox(container, "signing.decided")
    assert len(events) >= 1
    event = events[-1]
    data = event["data"]

    assert data["decision"] == "signed"
    assert data["object"]["kind"] == "quote"
    assert data["object"]["object_id"] == 42
    assert data["object"]["number"] == "КП-2026/042"
    assert data["signer"]["crm_user_id"] == staff["director"].id
    assert data["signer"]["full_name"] == staff["director"].name
    assert data["basis"] == "charter"
    assert len(data["verification_code"]) == 10
    assert "/v/" in data["verification_url"]
    assert data["signed_at"] is not None
    assert data["comment"] is None


async def test_commercial_signing_rejected_when_amount_exceeds_poa_limit(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    # 1. Выдаем бухгалтеру полномочие по доверенности с лимитом 10,000,000 UZS
    auth_resp = await client.post(
        URL_AUTHORITIES,
        json={
            "crm_user_id": staff["accountant"].id,
            "kinds": ["invoice", "act"],
            "limit_amount": "10000000.00",
            "limit_currency": "UZS",
            "basis": "power_of_attorney",
            "basis_number": "ДОВ-2026/01",
            "basis_date": "2026-01-01",
            "valid_from": "2026-01-01",
            "valid_to": "2027-01-01",
        },
        headers=staff["admin"].headers,
    )
    assert auth_resp.status_code == 201, auth_resp.text

    # 2. Доставляем запрос на подписание счета на 15,000,000 UZS (превышение лимита)
    envelope = signing_requested(
        kind="invoice",
        object_id=77,
        number="СЧ-2026/077",
        amount_tiyins=15_000_000_00,  # 15M UZS > 10M limit
        signer_crm_user_id=staff["accountant"].id,
        signer_name=staff["accountant"].name,
    )
    status = await deliver_erp(client, container, envelope)
    assert status == "processed"

    # 3. Проверяем outbox: событие signing.decided со статусом rejected
    events = await outbox(container, "signing.decided")
    event = events[-1]
    data = event["data"]

    assert data["decision"] == "rejected"
    assert data["object"]["kind"] == "invoice"
    assert data["object"]["object_id"] == 77
    assert data["verification_code"] is None
    assert data["comment"] is not None
    assert "превышает" in data["comment"]


async def test_commercial_signing_rejected_when_no_authority_for_kind(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    # Менеджер без полномочий пытается подписать договор
    envelope = signing_requested(
        kind="contract",
        object_id=99,
        number="ДОГ-2026/099",
        amount_tiyins=1_000_000_00,
        signer_crm_user_id=staff["manager"].id,
        signer_name=staff["manager"].name,
    )
    status = await deliver_erp(client, container, envelope)
    assert status == "processed"

    events = await outbox(container, "signing.decided")
    event = events[-1]
    data = event["data"]

    assert data["decision"] == "rejected"
    assert data["object"]["kind"] == "contract"
    assert data["verification_code"] is None
    assert data["comment"] is not None

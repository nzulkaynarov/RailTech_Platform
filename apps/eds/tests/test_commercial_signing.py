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


async def _open_ids(client: httpx.AsyncClient, staff: dict[str, Person]) -> list[str]:
    resp = await client.get(
        "/api/v1/approvals", params={"template": ["signing"], "status": ["open"]}, headers=staff["director"].headers
    )
    assert resp.status_code == 200, resp.text
    return [item["id"] for item in resp.json()["items"]]


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

    # 3. Сам запрос ничего не подписывает: шаг «Подписать» ждёт живого уполномоченного
    assert await outbox(container, "signing.decided") == []
    approval_id = (await _open_ids(client, staff))[0]

    decided = await client.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=staff["director"].headers
    )
    assert decided.status_code == 200, decided.text

    events = await outbox(container, "signing.decided")
    assert len(events) == 1
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


async def _grant_director(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    resp = await client.post(
        URL_AUTHORITIES,
        json={
            "crm_user_id": staff["director"].id,
            "kinds": ["quote", "contract", "invoice", "act"],
            "basis": "charter",
            "valid_from": "2026-01-01",
        },
        headers=staff["admin"].headers,
    )
    assert resp.status_code == 201, resp.text


def _request(staff: dict[str, Person], **extra: Any) -> dict[str, Any]:
    return signing_requested(
        kind="contract",
        object_id=500,
        number="Д-500",
        signer_crm_user_id=staff["director"].id,
        signer_name=staff["director"].name,
        **extra,
    )


async def test_repeat_of_an_open_request_opens_nothing_new(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await _grant_director(client, staff)
    await deliver_erp(client, container, _request(staff))
    await deliver_erp(client, container, _request(staff))
    assert len(await _open_ids(client, staff)) == 1
    assert await outbox(container, "signing.decided") == []


async def test_signed_version_cannot_be_signed_again(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await _grant_director(client, staff)
    await deliver_erp(client, container, _request(staff))
    [approval_id] = await _open_ids(client, staff)
    await client.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=staff["director"].headers
    )

    await deliver_erp(client, container, _request(staff))

    decided = await outbox(container, "signing.decided")
    assert [e["data"]["decision"] for e in decided] == ["signed", "rejected"]
    assert "уже подписана" in decided[-1]["data"]["comment"]


async def test_only_the_assigned_signer_can_sign(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await _grant_director(client, staff)
    await deliver_erp(client, container, _request(staff))
    [approval_id] = await _open_ids(client, staff)
    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=staff["accountant"].headers
    )
    assert resp.status_code in (403, 404), resp.text
    assert await outbox(container, "signing.decided") == []


async def test_refusal_reaches_the_author_with_the_reason(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await _grant_director(client, staff)
    await deliver_erp(client, container, _request(staff))
    [approval_id] = await _open_ids(client, staff)
    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "reject", "comment": "Неверные реквизиты"},
        headers=staff["director"].headers,
    )
    assert resp.status_code == 200, resp.text
    [event] = await outbox(container, "signing.decided")
    assert event["data"]["decision"] == "rejected"
    assert event["data"]["comment"] == "Неверные реквизиты"


async def test_authority_revoked_before_signing_blocks_the_signature(
    client: httpx.AsyncClient, container: Container, staff: dict[str, Person]
) -> None:
    await _grant_director(client, staff)
    await deliver_erp(client, container, _request(staff))
    [approval_id] = await _open_ids(client, staff)
    listed = await client.get(URL_AUTHORITIES, headers=staff["admin"].headers)
    authority = listed.json()["items"][0]["id"]
    revoked = await client.post(
        f"{URL_AUTHORITIES}/{authority}/revoke", json={"reason": "Уволен"}, headers=staff["admin"].headers
    )
    assert revoked.status_code == 200, revoked.text

    resp = await client.post(
        f"/api/v1/approvals/{approval_id}/decision", json={"decision": "approve"}, headers=staff["director"].headers
    )

    assert resp.status_code == 409, resp.text
    assert await outbox(container, "signing.decided") == []

"""Подпись исходящего письма в тестах: с 2026-11-21 номер выдаёт только `POST /documents/{id}/sign` (СЦ-9)."""

import httpx

from tests.domain import Person

AUTHORITIES = "/api/v1/signing/authorities"


async def ensure_signer(client: httpx.AsyncClient, staff: dict[str, Person], who: str = "registrar") -> None:
    """Подписант по реестру полномочий: `who` (делопроизводитель) вправе подписывать `letter_out` (один раз на тест)."""
    found = await client.get(AUTHORITIES, params={"crm_user_id": staff[who].id}, headers=staff["admin"].headers)
    assert found.status_code == 200, found.text
    if any("letter_out" in a["kinds"] for a in found.json()["items"]):
        return
    body = {"crm_user_id": staff[who].id, "kinds": ["letter_out"], "basis": "charter", "valid_from": "2026-01-01"}
    created = await client.post(AUTHORITIES, json=body, headers=staff["admin"].headers)
    assert created.status_code == 201, created.text


async def sign_out(
    client: httpx.AsyncClient,
    staff: dict[str, Person],
    document_id: str,
    *,
    send: bool = False,
    who: str = "registrar",
) -> httpx.Response:
    """Подписать письмо сотрудником `who` (делопроизводитель): номер, статус `sent`; `send` — и отправка."""
    await ensure_signer(client, staff, who)
    return await client.post(f"/api/v1/documents/{document_id}/sign", json={"send": send}, headers=staff[who].headers)

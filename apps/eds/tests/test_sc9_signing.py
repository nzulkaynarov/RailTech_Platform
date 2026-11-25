"""СЦ-9, подпись письма (pg): вычисленный подписант, `Document.signing` (кнопка и действие — одна проверка
`documents.sign_check`), задача «Подписать» только подписанту, первые тесты `POST /documents/{id}/sign`."""

from datetime import timedelta
from typing import Any

import httpx
import pytest
from sqlalchemy import text

from app import clock
from app.container import Container
from app.services import signing_resolve
from tests.domain import Person, validate
from tests.test_api_auth import assert_error
from tests.test_letterhead_letters import PAIR, deliver_letterhead
from tests.test_reply_path import reply_draft, tasks_of

pytestmark = pytest.mark.pg

URL_AUTHORITIES = "/api/v1/signing/authorities"


async def grant(client: httpx.AsyncClient, staff: dict[str, Person], who: str, **changes: Any) -> None:
    body = {"crm_user_id": staff[who].id, "kinds": ["letter_out"], "basis": "charter", "valid_from": "2026-01-01"}
    created = await client.post(URL_AUTHORITIES, json={**body, **changes}, headers=staff["admin"].headers)
    assert created.status_code == 201, created.text


async def draft_of(client: httpx.AsyncClient, who: Person) -> dict[str, Any]:
    return await reply_draft(client, who, None)


async def card(client: httpx.AsyncClient, who: Person, document_id: str) -> dict[str, Any]:
    found = await client.get(f"/api/v1/documents/{document_id}", headers=who.headers)
    assert found.status_code == 200, found.text
    body: dict[str, Any] = found.json()
    validate("Document", body)
    return body


async def hand_over(client: httpx.AsyncClient, who: Person, document_id: str) -> None:
    handed = await client.post(f"/api/v1/documents/{document_id}/registration-request", headers=who.headers)
    assert handed.status_code == 200, handed.text


async def test_sign_without_any_authority_is_refused_on_a_fresh_install(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc = await draft_of(client, staff["manager"])
    await hand_over(client, staff["manager"], doc["id"])
    refused = await client.post(f"/api/v1/documents/{doc['id']}/sign", headers=staff["director"].headers)
    assert_error(refused, 403, "FORBIDDEN")
    assert refused.json()["details"]["reason"] == "no_authority"
    # Та же проверка у кнопки: подписать нельзя, подписанта нет.
    assert (await card(client, staff["director"], doc["id"]))["signing"] == {
        "can_sign": False,
        "reason": "no_authority",
        "signer": None,
        "signer_position": None,
    }


async def test_author_with_authority_cannot_sign_while_another_signer_exists_under_the_strict_rule(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    saved = await client.patch(
        "/api/v1/docflow-settings", json={"author_may_sign_own_letter": False}, headers=staff["admin"].headers
    )
    assert saved.status_code == 200, saved.text
    await grant(client, staff, "registrar")
    await grant(client, staff, "director")
    doc = await draft_of(client, staff["registrar"])
    refused = await client.post(f"/api/v1/documents/{doc['id']}/sign", headers=staff["registrar"].headers)
    assert_error(refused, 409, "CONFLICT")
    assert refused.json()["details"]["reason"] == "author_cannot_sign"
    signing = (await card(client, staff["registrar"], doc["id"]))["signing"]
    assert signing["can_sign"] is False and signing["reason"] == "author_cannot_sign"
    assert signing["signer"] == {"crm_user_id": 3, "full_name": "Рустам Директоров"}


async def test_sole_signer_may_sign_own_letter(client: httpx.AsyncClient, staff: dict[str, Person]) -> None:
    await grant(client, staff, "registrar")
    doc = await draft_of(client, staff["registrar"])
    signing = (await card(client, staff["registrar"], doc["id"]))["signing"]
    assert (signing["can_sign"], signing["reason"], signing["signer"]["crm_user_id"]) == (True, None, 4)


async def test_signing_gives_number_and_sent_status_and_the_card_stops_offering_it(
    client: httpx.AsyncClient,
    staff: dict[str, Person],
    container: Container,
    deferred: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR)
    await deliver_letterhead(client, container)
    await grant(client, staff, "director")
    doc = await draft_of(client, staff["manager"])
    await hand_over(client, staff["manager"], doc["id"])
    before = (await card(client, staff["director"], doc["id"]))["signing"]
    assert (before["can_sign"], before["signer"]["crm_user_id"]) == (True, 3)

    signed = await client.post(
        f"/api/v1/documents/{doc['id']}/sign", json={"send": False}, headers=staff["director"].headers
    )
    assert signed.status_code == 200, signed.text
    body = signed.json()
    validate("Document", body)
    assert body["status"] == "sent" and body["number"] and body["signed_by"]["crm_user_id"] == 3
    assert body["signing"] is None  # подписанное письмо подпись больше не предлагает
    assert (await tasks_of(client, staff["director"]))["signatures"] == []


async def test_signature_task_goes_only_to_the_computed_signer_and_registrations_are_gone(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await grant(client, staff, "director")
    doc = await draft_of(client, staff["manager"])
    assert (await tasks_of(client, staff["director"]))["signatures"] == []  # пока не передано
    await hand_over(client, staff["manager"], doc["id"])

    [task] = (await tasks_of(client, staff["director"]))["signatures"]
    assert (task["document_id"], task["requested_by"]["crm_user_id"], task["acting_for"]) == (doc["id"], 5, None)
    for other in ("registrar", "manager", "accountant"):
        assert (await tasks_of(client, staff[other]))["signatures"] == [], other
    # Строки «Зарегистрировать» больше нет ни у кого: письмо без подписи не регистрируется.
    for name in ("registrar", "director", "manager"):
        assert (await tasks_of(client, staff[name]))["registrations"] == [], name


async def test_no_signer_means_no_signature_task_for_anyone(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc = await draft_of(client, staff["manager"])
    await hand_over(client, staff["manager"], doc["id"])
    for name in staff:
        assert (await tasks_of(client, staff[name]))["signatures"] == [], name


async def test_signature_task_goes_to_the_deputy_with_acting_for(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await grant(client, staff, "director")
    await grant(client, staff, "registrar", basis="order", basis_number="7", basis_date="2026-01-02")
    today = clock.company_date(clock.now())
    async with container.session_factory() as session, session.begin():
        await session.execute(
            text("UPDATE employees SET deputy_crm_user_id = 4, deputy_from = :a, deputy_to = :b WHERE crm_user_id = 3"),
            {"a": today - timedelta(days=1), "b": today + timedelta(days=3)},
        )
    doc = await draft_of(client, staff["manager"])
    await hand_over(client, staff["manager"], doc["id"])
    assert (await tasks_of(client, staff["director"]))["signatures"] == []  # директор отсутствует
    [task] = (await tasks_of(client, staff["registrar"]))["signatures"]
    assert task["acting_for"] == {"crm_user_id": 3, "full_name": "Рустам Директоров"}


async def test_letter_signer_skips_the_author_but_falls_back_to_the_only_candidate(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    from app.models import Document

    today = clock.company_date(clock.now())
    doc = await draft_of(client, staff["registrar"])
    async with container.session_factory() as session:
        row = await session.get(Document, doc["id"])
        assert row is not None
        assert await signing_resolve.letter_signer(session, row, today) is None
    await grant(client, staff, "registrar")
    async with container.session_factory() as session:
        row = await session.get(Document, doc["id"])
        assert row is not None
        solo = await signing_resolve.letter_signer(session, row, today)
        assert solo is not None and solo.signer.crm_user_id == 4  # автор — единственный кандидат
    await grant(client, staff, "director")
    async with container.session_factory() as session:
        row = await session.get(Document, doc["id"])
        assert row is not None
        other = await signing_resolve.letter_signer(session, row, today)
        assert other is not None and other.signer.crm_user_id == 3


async def test_card_of_an_author_without_signing_right_still_names_the_signer(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await grant(client, staff, "director")
    doc = await draft_of(client, staff["manager"])
    expected = {
        "can_sign": False,
        "reason": "no_permission",
        "signer": {"crm_user_id": 3, "full_name": "Рустам Директоров"},
        "signer_position": "Менеджер по продажам",
    }
    assert (await card(client, staff["manager"], doc["id"]))["signing"] == expected
    await hand_over(client, staff["manager"], doc["id"])
    assert (await card(client, staff["manager"], doc["id"]))["signing"] == expected


async def test_authority_holder_without_letters_register_is_the_signer(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    # СОТР-1: бухгалтер без letters.register видит переданный черновик и становится подписантом (реестр — правда).
    await grant(client, staff, "accountant")
    doc = await draft_of(client, staff["manager"])
    await hand_over(client, staff["manager"], doc["id"])
    assert len((await tasks_of(client, staff["accountant"]))["signatures"]) == 1
    for name in staff:
        if name != "accountant":
            assert (await tasks_of(client, staff[name]))["signatures"] == [], name
    assert (await card(client, staff["director"], doc["id"]))["signing"]["signer"]["crm_user_id"] == 6
    # Директор с полномочием по приказу: устав выше приказа, задача остаётся у бухгалтера.
    await grant(client, staff, "director", basis="order", basis_number="1", basis_date="2026-01-02")
    assert len((await tasks_of(client, staff["accountant"]))["signatures"]) == 1
    assert (await tasks_of(client, staff["director"]))["signatures"] == []

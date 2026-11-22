"""ГЛ-0, письмо «На подписи» без тупика (pg): настройка «автор подписывает своё письмо», один круг кандидатов у выбора
подписанта и проверки подписи, «Напомнить», «Отозвать», «Сменить подписанта», подписант в реестре."""

from typing import Any

import httpx
import pytest

from app.container import Container
from app.services import signing_resolve
from tests.conftest import FakeClock
from tests.domain import Person
from tests.test_api_auth import assert_error
from tests.test_document_notices import notices
from tests.test_ed6_signer import DIRECTOR, REGISTRAR, draft_with
from tests.test_letterhead_letters import PAIR, deliver_letterhead
from tests.test_reply_path import tasks_of
from tests.test_sc9_signing import card, draft_of, grant, hand_over

pytestmark = pytest.mark.pg

SETTINGS = "/api/v1/docflow-settings"


async def set_rule(client: httpx.AsyncClient, staff: dict[str, Person], *, author_may_sign: bool) -> None:
    saved = await client.patch(
        SETTINGS, json={"author_may_sign_own_letter": author_may_sign}, headers=staff["admin"].headers
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["author_may_sign_own_letter"] is author_may_sign


async def sign(client: httpx.AsyncClient, who: Person, document_id: str) -> httpx.Response:
    return await client.post(f"/api/v1/documents/{document_id}/sign", json={"send": False}, headers=who.headers)


# --- setting ---------------------------------------------------------------------------------------------------


async def test_setting_defaults_to_on_and_patch_changes_only_the_sent_field(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    shown = await client.get(SETTINGS, headers=staff["registrar"].headers)
    assert shown.status_code == 200 and shown.json()["author_may_sign_own_letter"] is True
    recognize = shown.json()["recognize_scans"]
    await set_rule(client, staff, author_may_sign=False)
    after = (await client.get(SETTINGS, headers=staff["registrar"].headers)).json()
    assert (after["author_may_sign_own_letter"], after["recognize_scans"]) == (False, recognize)
    # The other switch leaves the rule alone.
    other = await client.patch(SETTINGS, json={"recognize_scans": not recognize}, headers=staff["admin"].headers)
    assert other.status_code == 200 and other.json()["author_may_sign_own_letter"] is False
    denied = await client.patch(SETTINGS, json={"author_may_sign_own_letter": True}, headers=staff["registrar"].headers)
    assert denied.status_code == 403, denied.text


# --- one rule, one pool ----------------------------------------------------------------------------------------


async def test_with_the_setting_on_the_author_signs_own_letter_while_the_queue_goes_to_the_computed_signer(
    client: httpx.AsyncClient,
    staff: dict[str, Person],
    container: Container,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RT_BUS_SECRET_EDS_CRM", PAIR)
    await deliver_letterhead(client, container)
    await grant(client, staff, "director")
    await grant(client, staff, "registrar")
    doc = await draft_of(client, staff["registrar"])
    await hand_over(client, staff["registrar"], doc["id"])
    signing = (await card(client, staff["registrar"], doc["id"]))["signing"]
    # The author may sign, the computed signer is still the other holder: the task goes to the director.
    assert (signing["can_sign"], signing["reason"], signing["signer"]["crm_user_id"]) == (True, None, DIRECTOR)
    assert len((await tasks_of(client, staff["director"]))["signatures"]) == 1
    assert (await tasks_of(client, staff["registrar"]))["signatures"] == []
    signed = await sign(client, staff["registrar"], doc["id"])
    assert signed.status_code == 200, signed.text
    assert signed.json()["status"] == "sent" and signed.json()["signed_by"]["crm_user_id"] == REGISTRAR
    assert (await tasks_of(client, staff["director"]))["signatures"] == []  # the task disappears with the fact


async def test_with_the_setting_off_the_author_is_refused_and_the_card_names_who_signs(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await set_rule(client, staff, author_may_sign=False)
    await grant(client, staff, "director")
    await grant(client, staff, "registrar")
    doc = await draft_of(client, staff["registrar"])
    refused = await sign(client, staff["registrar"], doc["id"])
    assert_error(refused, 409, "CONFLICT")
    assert refused.json()["details"]["reason"] == "author_cannot_sign"
    signing = (await card(client, staff["registrar"], doc["id"]))["signing"]
    assert (signing["can_sign"], signing["reason"], signing["signer"]["crm_user_id"]) == (
        False,
        "author_cannot_sign",
        3,
    )
    assert "signer_position" in signing


async def test_strict_rule_counts_the_same_pool_as_the_signer_pick(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    """The accountant holds an authority but cannot open a handed-over draft (no letters.register): he is not in the
    pool, so he is neither the computed signer nor a reason to refuse the author. Before ГЛ-0 it counted him."""
    await set_rule(client, staff, author_may_sign=False)
    await grant(client, staff, "registrar")
    await grant(client, staff, "accountant")
    doc = await draft_of(client, staff["registrar"])
    signing = (await card(client, staff["registrar"], doc["id"]))["signing"]
    assert (signing["can_sign"], signing["reason"], signing["signer"]["crm_user_id"]) == (True, None, REGISTRAR)


async def test_strict_rule_lets_the_only_holder_in_the_pool_sign(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await set_rule(client, staff, author_may_sign=False)
    await grant(client, staff, "registrar")
    doc = await draft_of(client, staff["registrar"])
    signing = (await card(client, staff["registrar"], doc["id"]))["signing"]
    assert (signing["can_sign"], signing["signer"]["crm_user_id"]) == (True, REGISTRAR)


async def test_the_computed_signer_is_never_somebody_the_check_refuses(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    """The choice of the author as signer is skipped under the strict rule while the pool has someone else."""
    await grant(client, staff, "director")
    await grant(client, staff, "registrar")
    doc = await draft_with(client, staff["registrar"], REGISTRAR)  # setting ON: the author may choose himself
    assert doc["letter"]["signer_crm_user_id"] == REGISTRAR
    assert (await card(client, staff["registrar"], doc["id"]))["signing"]["signer"]["crm_user_id"] == REGISTRAR
    await set_rule(client, staff, author_may_sign=False)  # later the company turns the rule on
    signing = (await card(client, staff["registrar"], doc["id"]))["signing"]
    assert (signing["can_sign"], signing["reason"], signing["signer"]["crm_user_id"]) == (
        False,
        "author_cannot_sign",
        DIRECTOR,
    )


def test_pick_skips_a_chosen_author_only_under_the_strict_rule() -> None:
    from tests.test_signing_resolve import DEPUTY, run
    from tests.test_signing_resolve import DIRECTOR as HEAD
    from tests.test_signing_resolve import grant as holder_grant

    result = run([holder_grant(HEAD), holder_grant(DEPUTY)])
    kept = signing_resolve.pick_letter_signer(result, DEPUTY, None, DEPUTY, author_may_sign=True)
    skipped = signing_resolve.pick_letter_signer(result, DEPUTY, None, DEPUTY, author_may_sign=False)
    assert kept is not None and kept.signer.crm_user_id == DEPUTY
    assert skipped is not None and skipped.signer.crm_user_id == HEAD


async def test_the_author_may_choose_themselves_only_with_the_setting_on(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    await grant(client, staff, "director")
    await grant(client, staff, "registrar")
    from tests.test_letterhead_letters import letter_json

    body = letter_json()
    body["letter"]["signer_crm_user_id"] = REGISTRAR
    allowed = await client.post("/api/v1/documents", json=body, headers=staff["registrar"].headers)
    assert allowed.status_code == 201, allowed.text
    await set_rule(client, staff, author_may_sign=False)
    refused = await client.post("/api/v1/documents", json=body, headers=staff["registrar"].headers)
    assert refused.status_code == 422 and "author_cannot_sign" in refused.text


# --- notices ---------------------------------------------------------------------------------------------------


async def test_no_notice_when_the_author_is_the_signer_and_the_card_says_so(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await grant(client, staff, "registrar")
    doc = await draft_of(client, staff["registrar"])
    await hand_over(client, staff["registrar"], doc["id"])
    assert await notices(container, "letter_sign_requested") == []
    assert await notices(container, "letter_signer_missing") == []
    handed = await card(client, staff["registrar"], doc["id"])
    assert handed["signing"]["signer"]["crm_user_id"] == REGISTRAR and handed["awaiting_signature"] is True


# --- remind ----------------------------------------------------------------------------------------------------


async def handed_by_manager(client: httpx.AsyncClient, staff: dict[str, Person]) -> dict[str, Any]:
    await grant(client, staff, "director")
    await grant(client, staff, "registrar")
    doc = await draft_of(client, staff["manager"])
    await hand_over(client, staff["manager"], doc["id"])
    return doc


async def test_remind_resends_the_request_to_the_current_signer_once_an_hour(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container, clock: FakeClock
) -> None:
    doc = await handed_by_manager(client, staff)
    url = f"/api/v1/documents/{doc['id']}/remind"
    assert len(await notices(container, "letter_sign_requested")) == 1
    first = await client.post(url, headers=staff["manager"].headers)
    assert first.status_code == 200, first.text
    sent = await notices(container, "letter_sign_requested")
    assert len(sent) == 2 and sent[1]["recipients"] == [REGISTRAR]
    assert len({n["notice_key"] for n in sent}) == 2  # the repeat has its own key, CRM does not swallow it

    too_soon = await client.post(url, headers=staff["manager"].headers)
    assert_error(too_soon, 409, "CONFLICT")
    assert too_soon.json()["details"]["reason"] == "remind_too_soon" and "retry_at" in too_soon.json()["details"]
    assert len(await notices(container, "letter_sign_requested")) == 2

    clock.advance(minutes=61)
    later = await client.post(url, headers=staff["manager"].headers)
    assert later.status_code == 200, later.text
    assert len(await notices(container, "letter_sign_requested")) == 3
    actions = [e["action"] for e in (await card(client, staff["manager"], doc["id"]))["journal"]]
    assert actions.count("document.sign_reminded") == 2


async def test_remind_is_for_the_author_of_a_handed_over_letter_only(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc = await handed_by_manager(client, staff)
    url = f"/api/v1/documents/{doc['id']}/remind"
    assert_error(await client.post(url, headers=staff["registrar"].headers), 403, "FORBIDDEN")
    plain = await draft_of(client, staff["manager"])  # not handed over
    refused = await client.post(f"/api/v1/documents/{plain['id']}/remind", headers=staff["manager"].headers)
    assert_error(refused, 409, "CONFLICT")
    assert refused.json()["details"]["reason"] == "not_handed_over"


# --- withdraw --------------------------------------------------------------------------------------------------


async def test_withdraw_clears_the_handover_and_the_task_of_the_signer(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc = await handed_by_manager(client, staff)
    assert len((await tasks_of(client, staff["registrar"]))["signatures"]) == 1
    assert_error(
        await client.post(f"/api/v1/documents/{doc['id']}/withdraw", headers=staff["director"].headers),
        403,
        "FORBIDDEN",
    )
    done = await client.post(f"/api/v1/documents/{doc['id']}/withdraw", headers=staff["manager"].headers)
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["awaiting_signature"] is False and body["letter"]["registration_requested"] is None
    assert body["status"] == "draft"
    assert (await tasks_of(client, staff["registrar"]))["signatures"] == []
    journal = [e for e in body["journal"] if e["action"] == "document.registration_withdrawn"]
    assert len(journal) == 1 and journal[0]["comment"] == "Отозвано с подписи"
    again = await client.post(f"/api/v1/documents/{doc['id']}/withdraw", headers=staff["manager"].headers)
    assert_error(again, 409, "CONFLICT")
    # The author can hand it over again.
    await hand_over(client, staff["manager"], doc["id"])
    assert len((await tasks_of(client, staff["registrar"]))["signatures"]) == 1


async def test_withdraw_tells_the_former_signer(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    doc = await handed_by_manager(client, staff)
    assert await notices(container, "letter_sign_withdrawn") == []
    done = await client.post(f"/api/v1/documents/{doc['id']}/withdraw", headers=staff["manager"].headers)
    assert done.status_code == 200, done.text
    sent = await notices(container, "letter_sign_withdrawn")
    assert len(sent) == 1 and sent[0]["recipients"] == [REGISTRAR]
    assert sent[0]["title"] == "Письмо отозвано с подписи"


async def test_withdraw_is_silent_when_the_author_is_the_signer(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    await grant(client, staff, "registrar")
    doc = await draft_of(client, staff["registrar"])
    await hand_over(client, staff["registrar"], doc["id"])
    done = await client.post(f"/api/v1/documents/{doc['id']}/withdraw", headers=staff["registrar"].headers)
    assert done.status_code == 200, done.text
    assert await notices(container, "letter_sign_withdrawn") == []


# --- change signer ---------------------------------------------------------------------------------------------


async def test_change_signer_moves_the_task_and_notifies_the_new_signer_once(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    doc = await handed_by_manager(client, staff)
    url = f"/api/v1/documents/{doc['id']}/signer"
    changed = await client.post(url, json={"signer_crm_user_id": DIRECTOR}, headers=staff["manager"].headers)
    assert changed.status_code == 200, changed.text
    assert changed.json()["letter"]["signer_crm_user_id"] == DIRECTOR
    assert changed.json()["signing"]["signer"]["crm_user_id"] == DIRECTOR
    assert (await tasks_of(client, staff["registrar"]))["signatures"] == []
    assert len((await tasks_of(client, staff["director"]))["signatures"]) == 1
    sent = await notices(container, "letter_sign_requested")
    assert [n["recipients"] for n in sent] == [[REGISTRAR], [DIRECTOR]]
    # The same choice again changes nothing and does not notify.
    same = await client.post(url, json={"signer_crm_user_id": DIRECTOR}, headers=staff["manager"].headers)
    assert same.status_code == 200
    assert len(await notices(container, "letter_sign_requested")) == 2
    refused = await client.post(
        url, json={"signer_crm_user_id": staff["accountant"].id}, headers=staff["manager"].headers
    )
    assert refused.status_code == 422 and "no_signing_right" in refused.text
    assert_error(await client.post(url, json={}, headers=staff["registrar"].headers), 403, "FORBIDDEN")


async def test_editing_the_signer_of_a_handed_over_letter_notifies_the_new_one(
    client: httpx.AsyncClient, staff: dict[str, Person], container: Container
) -> None:
    from tests.test_letterhead_letters import letter_json

    doc = await handed_by_manager(client, staff)
    letter = {**letter_json()["letter"], "signer_crm_user_id": DIRECTOR}
    saved = await client.patch(
        f"/api/v1/documents/{doc['id']}", json={"letter": letter}, headers=staff["manager"].headers
    )
    assert saved.status_code == 200, saved.text
    assert [n["recipients"] for n in await notices(container, "letter_sign_requested")] == [[REGISTRAR], [DIRECTOR]]


# --- registry --------------------------------------------------------------------------------------------------


async def test_registry_row_of_a_letter_on_signing_shows_the_signer(
    client: httpx.AsyncClient, staff: dict[str, Person]
) -> None:
    doc = await handed_by_manager(client, staff)
    page = await client.get("/api/v1/registry", params={"stage": "open"}, headers=staff["director"].headers)
    assert page.status_code == 200, page.text
    [row] = [r for r in page.json()["items"] if r["id"] == doc["id"]]
    assert row["awaiting_signature"] is True and row["signer"]["crm_user_id"] == REGISTRAR
    await client.post(
        f"/api/v1/documents/{doc['id']}/signer",
        json={"signer_crm_user_id": REGISTRAR},
        headers=staff["manager"].headers,
    )
    page = await client.get("/api/v1/registry", params={"stage": "open"}, headers=staff["director"].headers)
    [row] = [r for r in page.json()["items"] if r["id"] == doc["id"]]
    assert row["signer"]["crm_user_id"] == REGISTRAR

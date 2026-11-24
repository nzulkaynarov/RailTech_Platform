"""Ручки лида (LH-1, контракт BFF, теги `messages` и `leads`): закрыть, передать коллеге, отбросить,
открыть заново, «Принято к сведению», отложить, правка контактов.

CRM — на respx (`messages_support`), ответы сверяются со схемами platform-bff.yaml. BFF проверяет
раздел `crm.leads: full` до CRM, передаёт токен сотрудника и тело для CRM, выбирает действие
«Открыть заново» по стадии и переводит отказы CRM (подкод, поле формы); чужой лид — 404 или 403.
"""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.messages_support import CrmMessagesFake, lead_detail

BASE = "/api/v1/crm/messages"
LEAD = "/api/v1/crm/leads"


@pytest.fixture
def crm(be: Backends) -> CrmMessagesFake:
    fake = CrmMessagesFake(be)
    for action in (
        "close_won",
        "close_lost",
        "assign",
        "discard",
        "new_deal",
        "acknowledge",
        "snooze",
        "unsnooze",
    ):
        fake.answer("POST", f"leads/2041/actions/{action}", body={"id": None, "ok": True})
    return fake


def calls_to(crm: CrmMessagesFake, path: str) -> int:
    return len(crm.to(path))


async def test_close_lost_sends_the_reason_to_crm_with_the_employee_token(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    done = await web.send(
        "POST", f"{BASE}/L-2041/close", json={"outcome": "lost", "lost_reason": "Дорого"}
    )
    check(done, "/crm/messages/{lead}/close", "post")
    assert done.status_code == 200
    request = crm.last("POST", "leads/2041/actions/close_lost")
    assert request.headers["authorization"].startswith("Bearer crm-access-")
    assert json.loads(request.content) == {"reason": None, "lost_reason": "Дорого"}


async def test_close_won_goes_to_close_won_and_erp_conflict_is_translated(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    ok = await web.send(
        "POST", f"{BASE}/L-2041/close", json={"outcome": "won", "reason": "договор"}
    )
    check(ok, "/crm/messages/{lead}/close", "post")
    assert crm.body("POST", "leads/2041/actions/close_won")["reason"] == "договор"

    crm.error("POST", "leads/2041/actions/close_won", 409, "conflict", reason="won_decided_by_erp")
    refused = check(
        await web.send("POST", f"{BASE}/L-2041/close", json={"outcome": "won"}),
        "/crm/messages/{lead}/close",
        "post",
    )
    assert (refused.status_code, refused.json()["details"]["reason"]) == (
        409,
        "won_decided_by_erp",
    )


async def test_close_lost_without_a_reason_is_rejected_before_crm(
    web: Web, crm: CrmMessagesFake
) -> None:
    await web.login(["MANAGER"])
    bare = await web.send("POST", f"{BASE}/L-2041/close", json={"outcome": "lost"})
    assert bare.status_code == 422
    assert crm.to("leads/2041/actions/close_lost") == []


async def test_close_options_come_from_crm(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    crm.answer(
        "GET",
        "leads/close_options",
        body={"lost_reasons": ["Дорого", "Выбрал другого"], "won_by_erp": True},
    )
    await web.login(["MANAGER"])
    response = check(
        await web.client.get("/api/v1/crm/lead-close-options"), "/crm/lead-close-options", "get"
    )
    assert response.json() == {"lost_reasons": ["Дорого", "Выбрал другого"], "won_by_erp": True}


async def test_assign_to_a_colleague_and_the_list_skips_myself(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    crm.answer(
        "GET",
        "team",
        body=[
            {"id": 7, "full_name": "Дилшод Менеджеров", "initials": "ДМ", "position": None},
            {"id": 9, "full_name": "Камила Демо", "initials": "КД", "position": None},
        ],
    )
    await web.login(["MANAGER"])
    colleagues = check(
        await web.client.get("/api/v1/crm/lead-colleagues"), "/crm/lead-colleagues", "get"
    )
    assert [p["id"] for p in colleagues.json()["items"]] == ["9"]
    done = await web.send("POST", f"{BASE}/L-2041/assign", json={"user_id": "9"})
    check(done, "/crm/messages/{lead}/assign", "post")
    assert crm.body("POST", "leads/2041/actions/assign") == {"user_id": 9}

    crm.error("POST", "leads/2041/actions/assign", 422, "validation", reason="inactive_colleague")
    refused = await web.send("POST", f"{BASE}/L-2041/assign", json={"user_id": "9"})
    assert (refused.status_code, refused.json()["details"]["reason"]) == (
        422,
        "inactive_colleague",
    )


@pytest.mark.parametrize("kind", ["spam", "test"])
async def test_discard_spam_and_test(
    web: Web, crm: CrmMessagesFake, check: ContractChecker, kind: str
) -> None:
    await web.login(["MANAGER"])
    done = await web.send("POST", f"{BASE}/L-2041/discard", json={"kind": kind})
    check(done, "/crm/messages/{lead}/discard", "post")
    assert crm.body("POST", "leads/2041/actions/discard") == {"kind": kind, "duplicate_of": None}


async def test_discard_duplicate_needs_the_kept_lead_and_translates_it(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    bare = await web.send("POST", f"{BASE}/L-2041/discard", json={"kind": "duplicate"})
    assert bare.status_code == 422
    stray = await web.send(
        "POST", f"{BASE}/L-2041/discard", json={"kind": "spam", "duplicate_of": "L-2050"}
    )
    assert stray.status_code == 422
    assert crm.to("leads/2041/actions/discard") == []
    done = await web.send(
        "POST", f"{BASE}/L-2041/discard", json={"kind": "duplicate", "duplicate_of": "L-2050"}
    )
    check(done, "/crm/messages/{lead}/discard", "post")
    assert crm.body("POST", "leads/2041/actions/discard") == {
        "kind": "duplicate",
        "duplicate_of": 2050,
    }
    crm.error("POST", "leads/2041/actions/discard", 422, "validation", field="duplicate_of")
    refused = await web.send(
        "POST", f"{BASE}/L-2041/discard", json={"kind": "duplicate", "duplicate_of": "L-2050"}
    )
    assert (refused.status_code, refused.json()["details"]["fields"]) == (422, ["duplicate_of"])


async def test_foreign_lead_is_not_found_or_forbidden_as_crm_says(
    web: Web, crm: CrmMessagesFake
) -> None:
    await web.login(["MANAGER"])
    # лида 2999 CRM не знает: 404 доходит до экрана, чужой лид не отличить от несуществующего
    for path, body in (
        ("close", {"outcome": "won"}),
        ("assign", {"user_id": "9"}),
        ("discard", {"kind": "spam"}),
        ("acknowledge", None),
        ("unsnooze", None),
    ):
        response = await web.send("POST", f"{BASE}/L-2999/{path}", json=body)
        assert response.status_code == 404, path
        assert response.json()["code"] == "NOT_FOUND", path
    crm.error("POST", "leads/2041/actions/close_won", 403, "forbidden", reason="not_lead_owner")
    foreign = await web.send("POST", f"{BASE}/L-2041/close", json={"outcome": "won"})
    assert (foreign.status_code, foreign.json()["details"]["reason"]) == (403, "not_lead_owner")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("close", {"outcome": "won"}),
        ("assign", {"user_id": "9"}),
        ("discard", {"kind": "spam"}),
        ("reopen", None),
        ("acknowledge", None),
        ("snooze", {"period": "day"}),
        ("unsnooze", None),
    ],
)
async def test_the_director_and_a_wrong_csrf_never_reach_crm(
    web: Web, crm: CrmMessagesFake, path: str, body: Any
) -> None:
    await web.login(["DIRECTOR"])
    denied = await web.send("POST", f"{BASE}/L-2041/{path}", json=body)
    assert denied.status_code == 403
    assert denied.json()["details"]["need"] == "full"
    await web.login(["MANAGER"])
    wrong = await web.client.post(
        f"{BASE}/L-2041/{path}", json=body, headers={CSRF_HEADER: "wrong-token-123456"}
    )
    assert wrong.status_code == 403
    assert not [c for c in crm.calls if c.method == "POST"]


async def test_reopen_picks_the_crm_action_by_the_stage(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    crm.answer("GET", "leads/2041", body=lead_detail(2041, stage="lost"))
    check(await web.send("POST", f"{BASE}/L-2041/reopen"), "/crm/messages/{lead}/reopen", "post")
    assert calls_to(crm, "leads/2041/actions/take") == 1
    assert calls_to(crm, "leads/2041/actions/new_deal") == 0

    crm.answer("GET", "leads/2041", body=lead_detail(2041, stage="customer"))
    check(await web.send("POST", f"{BASE}/L-2041/reopen"), "/crm/messages/{lead}/reopen", "post")
    assert calls_to(crm, "leads/2041/actions/new_deal") == 1

    crm.answer("GET", "leads/2041", body=lead_detail(2041, stage="in_progress"))
    open_lead = await web.send("POST", f"{BASE}/L-2041/reopen")
    assert (open_lead.status_code, open_lead.json()["details"]["reason"]) == (409, "not_closed")
    assert calls_to(crm, "leads/2041/actions/take") == 1
    assert calls_to(crm, "leads/2041/actions/new_deal") == 1


async def test_acknowledge_snooze_and_unsnooze_go_to_the_matching_crm_actions(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    check(
        await web.send("POST", f"{BASE}/L-2041/acknowledge"),
        "/crm/messages/{lead}/acknowledge",
        "post",
    )
    assert calls_to(crm, "leads/2041/actions/acknowledge") == 1
    before = datetime.now(UTC)
    done = await web.send("POST", f"{BASE}/L-2041/snooze", json={"period": "three_days"})
    check(done, "/crm/messages/{lead}/snooze", "post")
    until = datetime.fromisoformat(crm.body("POST", "leads/2041/actions/snooze")["until"])
    assert timedelta(days=3) - timedelta(minutes=1) < until - before < timedelta(days=3, minutes=1)
    check(
        await web.send("POST", f"{BASE}/L-2041/unsnooze"),
        "/crm/messages/{lead}/unsnooze",
        "post",
    )
    assert calls_to(crm, "leads/2041/actions/unsnooze") == 1
    crm.error("POST", "leads/2041/actions/acknowledge", 409, "conflict", reason="no_open_handoff")
    stale = await web.send("POST", f"{BASE}/L-2041/acknowledge")
    assert (stale.status_code, stale.json()["details"]["reason"]) == (409, "no_open_handoff")
    bad = await web.send("POST", f"{BASE}/L-2041/snooze", json={"period": "forever"})
    assert bad.status_code == 422


async def test_update_contacts_sends_only_named_fields_and_returns_duplicates(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    crm.answer(
        "PATCH",
        "leads/2041",
        body={
            "id": None,
            "ok": True,
            "duplicates": [
                {"kind": "lead", "id": 2050, "name": "Азиз", "field": "phone"},
                {"kind": "client", "id": 12, "name": "ООО Ромашка", "field": "email"},
            ],
        },
    )
    await web.login(["MANAGER"])
    done = check(
        await web.send("PATCH", f"{LEAD}/L-2041", json={"phone": "90 123 45 67", "company": ""}),
        "/crm/leads/{lead}",
        "patch",
    )
    assert crm.body("PATCH", "leads/2041") == {"phone": "90 123 45 67", "company": ""}
    assert done.json()["duplicates"] == [
        {"kind": "lead", "lead": "L-2050", "client_id": None, "name": "Азиз", "field": "phone"},
        {
            "kind": "client",
            "lead": None,
            "client_id": 12,
            "name": "ООО Ромашка",
            "field": "email",
        },
    ]


async def test_update_contacts_translates_the_field_error(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    crm.error("PATCH", "leads/2041", 422, "validation", reason="invalid_phone", field="phone")
    await web.login(["MANAGER"])
    refused = check(
        await web.send("PATCH", f"{LEAD}/L-2041", json={"phone": "12"}),
        "/crm/leads/{lead}",
        "patch",
    )
    assert refused.status_code == 422
    assert refused.json()["details"]["fields"] == ["phone"]
    assert refused.json()["details"]["reason"] == "invalid_phone"
    empty = await web.send("PATCH", f"{LEAD}/L-2041", json={})
    assert empty.status_code == 422
    await web.login(["DIRECTOR"])
    denied = await web.send("PATCH", f"{LEAD}/L-2041", json={"name": "Х"})
    assert denied.status_code == 403


async def test_card_shows_the_discard_mark(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    crm.answer(
        "GET",
        "leads/2041",
        body=lead_detail(2041, stage="lost", discarded_kind="duplicate", duplicate_of_lead_id=2050),
    )
    await web.login(["MANAGER"])
    card = check(await web.client.get(f"{LEAD}/L-2041"), "/crm/leads/{lead}", "get")
    assert (card.json()["discarded"], card.json()["duplicate_of"]) == ("duplicate", "L-2050")


async def test_duplicate_client_is_named_only_for_those_who_read_clients(
    web: Web, crm: CrmMessagesFake, monkeypatch: pytest.MonkeyPatch
) -> None:
    crm.answer(
        "PATCH",
        "leads/2041",
        body={
            "id": None,
            "ok": True,
            "duplicates": [{"kind": "client", "id": 12, "name": "ООО Ромашка", "field": "email"}],
        },
    )
    await web.login(["MANAGER"])
    seen = await web.send("PATCH", f"{LEAD}/L-2041", json={"email": "a@example.com"})
    assert seen.json()["duplicates"][0]["name"] == "ООО Ромашка"
    assert seen.json()["duplicates"][0]["client_id"] == 12
    # сотрудник без раздела клиентов: только вид дубля, без названия и ссылки на карточку
    monkeypatch.setattr("app.api.crm_lead_actions.allows", lambda *_args, **_kw: False)
    hidden = await web.send("PATCH", f"{LEAD}/L-2041", json={"email": "a@example.com"})
    assert hidden.json()["duplicates"] == [
        {"kind": "client", "lead": None, "client_id": None, "name": "", "field": "email"}
    ]

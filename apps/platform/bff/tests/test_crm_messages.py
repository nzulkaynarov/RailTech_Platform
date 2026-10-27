"""Клиенты · Ждут ответа (D1-1, контракт BFF 0.18.0, тег `messages`): прокси к CRM и подсказка SSE.

CRM — на respx (`messages_support`), ответы BFF сверяются со схемами platform-bff.yaml. Проверяется
то, что делает BFF: раздел каталога (`crm.leads` — чтение для очереди и ленты, полный для действий;
директор читает, но не забирает и не отвечает — 403 до CRM), токен сотрудника в CRM, словарь
(группы, режим, номер лида, `PersonRef`), что не уходит в браузер (ключ хранилища вложения,
служебная пометка причины, неизвестные коды), перевод отказов CRM в `Error`, и путь события
`lead.message_added` → подсказка `messages` в открытом потоке с замером времени.
"""

import json
import time

import pytest
from fastapi import FastAPI

from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.bus_support import CRM_SECRET, delivery, envelope
from tests.conftest import ContractChecker, Web
from tests.messages_support import CrmMessagesFake, escalation, lead
from tests.test_events_stream import Asgi, until

BASE = "/api/v1/crm/messages"


@pytest.fixture
def crm(be: Backends) -> CrmMessagesFake:
    return CrmMessagesFake(be)


# --- очередь -------------------------------------------------------------------------------------


async def test_inbox_groups_leads_once_with_the_handoff_note(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = check(await web.client.get(BASE), "/crm/messages", "get")

    items = response.json()["items"]
    assert [(i["lead"], i["group"]) for i in items] == [
        ("L-2041", "handoff"),
        ("L-2050", "mine"),
        ("L-2060", "unassigned"),
    ]
    first = items[0]
    assert first["handoff"]["priority"] == "hot"
    assert first["handoff"]["reasons"] == ["price_or_contract_asked"]  # мусорный код не уходит
    assert first["handoff"]["sla_due_at"] == "2026-10-27T09:03:00Z"
    assert first["note"] == {
        "request": "Рельсы Р65, 40 т",
        "facts": {
            "interest": ["Рельсы"],
            "timeline": "<3m",
            "decision_role": "decision_maker",
            "budget_hint": None,
            "company": "ООО Демо-Логистик",
            "company_size": None,
            "region": "unknown-code-is-text",
        },
        "last_message": "Сколько стоит?",
    }
    mine = items[1]
    assert mine["unread"] is True
    assert mine["assigned"] == {"id": "7", "name": "Дилшод Менеджеров", "initials": "ДМ"}
    assert items[2]["note"]["request"] == "Рельсы Р65, 40 т"  # без записки — резюме лида
    assert crm.last("GET", "inbox").headers["authorization"].startswith("Bearer crm-access-")


async def test_service_notes_of_the_reason_do_not_reach_the_screen(
    web: Web, crm: CrmMessagesFake
) -> None:
    crm.answer(
        "GET",
        "inbox",
        body={
            "escalations": [lead(2041, escalation=escalation(reason_text="dialog: no_kb_match"))],
            "mine": [],
            "unassigned": [],
        },
    )
    await web.login(["MANAGER"])
    item = (await web.client.get(BASE)).json()["items"][0]
    assert item["handoff"]["reason_text"] is None


async def test_without_the_leads_section_the_inbox_is_forbidden_before_crm(
    web: Web, crm: CrmMessagesFake
) -> None:
    await web.login(["SUPPLY"])
    response = await web.client.get(BASE)
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    assert response.json()["details"] == {"resource": "crm.leads", "need": "read"}
    assert crm.calls == []


async def test_director_reads_but_does_not_take_reply_or_use_templates(
    web: Web, crm: CrmMessagesFake
) -> None:
    await web.login(["DIRECTOR"])
    assert (await web.client.get(BASE)).status_code == 200
    assert (await web.client.get(f"{BASE}/L-2041/thread")).status_code == 200
    for path, body in (
        ("take", None),
        ("reply", {"text": "Добрый день", "client_message_id": "draft-0001"}),
        ("note", {"text": "x"}),
        ("assist", {"mode": "draft"}),
        ("return-to-bot", None),
    ):
        response = await web.send("POST", f"{BASE}/L-2041/{path}", json=body)
        assert response.status_code == 403, path
        assert response.json()["details"]["need"] == "full"
    assert (await web.client.get("/api/v1/crm/reply-templates")).status_code == 403
    assert not [c for c in crm.calls if c.method == "POST"]


async def test_crm_down_is_backend_unavailable(web: Web, crm: CrmMessagesFake) -> None:
    crm.answer("GET", "inbox", 503, {"code": "unavailable"})
    await web.login(["MANAGER"])
    response = await web.client.get(BASE)
    assert response.status_code == 503
    assert response.json()["code"] == "BACKEND_UNAVAILABLE"
    assert response.json()["source"] == "crm"


# --- карточка и лента ----------------------------------------------------------------------------


async def test_card_maps_contacts_facts_and_owner(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = check(await web.client.get(f"{BASE}/L-2041"), "/crm/messages/{lead}", "get")
    body = response.json()
    assert body["lead"] == "L-2041"
    assert body["owner_mode"] == "waiting"
    assert body["contacts"] == {
        "telegram": "aziz_demo",
        "phone": "+998900000000",
        "email": None,
        "company": "ООО Демо-Логистик",
    }
    assert body["facts"]["interest"] == ["Рельсы"]
    assert body["facts"]["decision_role"] is None  # неизвестный код роли — не показываем
    assert body["facts"]["company"] == "ООО Демо"
    assert body["handoff"]["state"] == "open"


async def test_unknown_lead_number_is_404(web: Web, crm: CrmMessagesFake) -> None:
    await web.login(["MANAGER"])
    assert (await web.client.get(f"{BASE}/L-9999")).status_code == 404
    assert (await web.client.get(f"{BASE}/ZV-1")).status_code == 422  # не номер лида


async def test_thread_hides_the_storage_key_and_names_the_manager(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    response = check(
        await web.client.get(f"{BASE}/L-2041/thread?limit=3"), "/crm/messages/{lead}/thread", "get"
    )
    body = response.json()
    assert [(m["id"], m["author"], m["author_name"]) for m in body["items"]] == [
        (90, "lead", None),
        (91, "bot", None),
        (92, "manager", "Дилшод Менеджеров"),
    ]
    assert body["items"][0]["attachments"] == [
        {
            "index": 0,
            "name": "Заявка.pdf",
            "mime": "application/pdf",
            "size": 1200,
            "url": "/api/v1/crm/messages/L-2041/attachments/90/0",
        },
        {"index": 1, "name": "big.zip", "mime": "application/zip", "size": None, "url": None},
    ]
    assert "storage_key" not in response.text
    assert "tg/5001" not in response.text
    assert body["has_more"] is True
    assert [n["author_name"] for n in body["notes"]] == ["Дилшод Менеджеров"]
    assert crm.last("GET", "leads/2041/messages").url.params["limit"] == "3"


async def test_older_page_asks_crm_before_id_and_skips_notes(
    web: Web, crm: CrmMessagesFake
) -> None:
    await web.login(["MANAGER"])
    body = (await web.client.get(f"{BASE}/L-2041/thread?before=90")).json()
    assert crm.last("GET", "leads/2041/messages").url.params["before_id"] == "90"
    assert body["notes"] == []
    assert body["has_more"] is False
    assert crm.to("leads/2041/notes") == []


async def test_attachment_is_relayed_as_a_download(web: Web, crm: CrmMessagesFake) -> None:
    await web.login(["DIRECTOR"])
    response = await web.client.get(f"{BASE}/L-2041/attachments/90/0")
    assert response.status_code == 200
    assert response.content == b"%PDF-1.4 demo"
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"
    missing = await web.client.get(f"{BASE}/L-2041/attachments/90/1")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"


# --- действия ------------------------------------------------------------------------------------


async def test_take_uses_the_employee_token_and_explains_who_took_it(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    ok = await web.send("POST", f"{BASE}/L-2041/take")
    check(ok, "/crm/messages/{lead}/take", "post")
    assert (
        crm.last("POST", "leads/2041/actions/take").headers["authorization"].startswith("Bearer ")
    )

    crm.error(
        "POST",
        "leads/2041/actions/take",
        409,
        "conflict",
        reason="lead_taken",
        assigned_user_name="Камила Демо",
    )
    taken = check(
        await web.send("POST", f"{BASE}/L-2041/take"), "/crm/messages/{lead}/take", "post"
    )
    assert taken.status_code == 409
    assert taken.json()["code"] == "CONFLICT"
    assert taken.json()["details"]["reason"] == "lead_taken"
    assert taken.json()["details"]["assigned_user_name"] == "Камила Демо"


async def test_reply_passes_the_retry_key_and_reports_telegram_failure(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    body = {"text": "Цена — в КП сегодня", "client_message_id": "draft-2041-abc123"}
    sent = check(
        await web.send("POST", f"{BASE}/L-2041/reply", json=body),
        "/crm/messages/{lead}/reply",
        "post",
    )
    assert sent.json() == {"id": 93}
    assert crm.body("POST", "leads/2041/messages") == body

    crm.error("POST", "leads/2041/messages", 502, "delivery_failed")
    failed = check(
        await web.send("POST", f"{BASE}/L-2041/reply", json=body),
        "/crm/messages/{lead}/reply",
        "post",
    )
    assert failed.status_code == 502
    assert failed.json()["code"] == "INTEGRATION_FAILED"
    assert failed.json()["source"] == "crm"
    assert failed.json()["details"]["reason"] == "delivery_failed"

    crm.error("POST", "leads/2041/messages", 409, "conflict", reason="take_first")
    first = await web.send("POST", f"{BASE}/L-2041/reply", json=body)
    assert (first.status_code, first.json()["details"]["reason"]) == (409, "take_first")

    bad = await web.send("POST", f"{BASE}/L-2041/reply", json={**body, "client_message_id": "x"})
    assert bad.status_code == 422


async def test_note_assist_return_and_templates(
    web: Web, crm: CrmMessagesFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    note = await web.send("POST", f"{BASE}/L-2041/note", json={"text": "Перезвонить после обеда"})
    check(note, "/crm/messages/{lead}/note", "post")
    assert (note.status_code, note.json()) == (201, {"id": 6})
    assert crm.body("POST", "leads/2041/actions/note") == {
        "text": "Перезвонить после обеда",
        "visible_to_bot": False,
    }

    hint = check(
        await web.send("POST", f"{BASE}/L-2041/assist", json={"mode": "draft"}),
        "/crm/messages/{lead}/assist",
        "post",
    )
    assert hint.json() == {"text": "Добрый день! Цену пришлём в КП сегодня.", "notice": None}
    crm.error("POST", "leads/2041/assist", 409, "conflict", reason="assist_disabled")
    off = await web.send("POST", f"{BASE}/L-2041/assist", json={"mode": "draft"})
    assert (off.status_code, off.json()["details"]["reason"]) == (409, "assist_disabled")

    back = await web.send("POST", f"{BASE}/L-2041/return-to-bot")
    check(back, "/crm/messages/{lead}/return-to-bot", "post")
    assert crm.body("POST", "leads/2041/actions/return_to_bot") == {"note": None}

    templates = check(
        await web.client.get("/api/v1/crm/reply-templates"), "/crm/reply-templates", "get"
    )
    assert templates.json()["items"][0]["title"] == "Приветствие"


async def test_actions_need_the_csrf_header(web: Web, crm: CrmMessagesFake) -> None:
    await web.login(["MANAGER"])
    response = await web.client.post(
        f"{BASE}/L-2041/take", headers={CSRF_HEADER: "wrong-token-123456"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    assert crm.to("leads/2041/actions/take") == []


# --- живые обновления: событие CRM → подсказка `messages` ----------------------------------------


async def test_a_client_message_reaches_the_open_stream_as_a_messages_hint_within_2s(
    web: Web, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Замер D1-1: приём события шины BFF → кадр `invalidate` в открытом потоке сотрудника.
    Окно слияния — боевое (300 мс): путь «бот записал сообщение → outbox → доставка →
    подсказка» на стороне BFF укладывается в него."""
    monkeypatch.setenv("RT_BUS_SECRET_CRM_PLATFORM_BFF", CRM_SECRET)
    app: FastAPI = web.app
    assert app.state.settings.events_coalesce_ms == 300
    assert (await web.login(["MANAGER"])).status_code == 200
    conn = Asgi(app, "/api/v1/events/stream", f"rt_pf_session={web.sid}")
    await until(lambda: conn.status == 200 and b": connected" in conn.body)
    await until(lambda: bool(web.redis.subscribers))

    headers, raw = delivery(
        envelope("crm", "lead.message_added"), publisher="crm", secret=CRM_SECRET
    )
    started = time.perf_counter()
    response = await web.client.post("/bus/v1/events", content=raw, headers=headers)
    assert response.status_code == 200
    await until(lambda: b"event: invalidate" in conn.body, seconds=2.0)
    elapsed = time.perf_counter() - started

    data = conn.body.decode().split("data: ", 1)[1].split("\n", 1)[0]
    assert json.loads(data) == {
        "topics": ["counters", "queue", "messages"],
        "reason": "uz.railtech.crm.lead.message_added.v1",
    }
    assert elapsed < 2.0
    print(f"D1-1 замер: событие шины → подсказка SSE за {elapsed * 1000:.0f} мс")  # noqa: T201
    await conn.disconnect()

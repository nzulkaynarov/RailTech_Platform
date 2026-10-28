"""«Доработать» в «Моей очереди» автора (D1-6b, контракт BFF): документ, который согласующий
вернул на доработку, — строка `rework_document` с кнопкой «Открыть» в форму «Продолжить».

EDS — на respx (`feeds_support.FeedBackends`): `GET /documents?mine=true&status=returned` и
карточка каждого документа (решение «Вернуть»: кто и что написал). Права — по токену `aud=eds`:
BFF не фильтрует чужие документы и ничего не решает, он передаёт `mine=true` и показывает ответ.
"""

import asyncio
import json
import time
from typing import Any

import httpx
import pytest

from app.feeds import rework as rework_module
from app.hub import CHANNEL
from tests.bus_support import delivery, envelope
from tests.conftest import ContractChecker, Web
from tests.eds_documents_support import EdsFake
from tests.feeds_support import FeedBackends, Moments, escalation, lead
from tests.roles import custom, rid

DOC_ID = "10000000-0000-4000-8000-000000000028"
OTHER_ID = "10000000-0000-4000-8000-000000000029"
DIRECTOR = {"crm_user_id": 3, "full_name": "Рустам Директоров"}
ME = {"crm_user_id": 7, "full_name": "Иван Тестов"}
EDS_SECRET = "test-pair-secret-eds-platform-bff"


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


def item(doc_id: str = DOC_ID, number: str = "СЗ-2026/028", **over: Any) -> dict[str, Any]:
    return {
        "id": doc_id,
        "kind": "memo",
        "number": number,
        "status": "returned",
        "subject": "Командировка в Самарканд",
        "author": ME,
        "amount": None,
        "due_date": None,
        "created_at": "2027-01-10T09:00:00Z",
        **over,
    }


def card(doc_id: str = DOC_ID, *decisions: dict[str, Any], **over: Any) -> dict[str, Any]:
    return {**item(doc_id, **over), "decisions": list(decisions)}


def returned(
    comment: str | None, at: str = "2027-01-14T04:00:00Z", *, round_: int = 1
) -> dict[str, Any]:
    return {
        "round": round_,
        "step": 1,
        "decision": "return",
        "comment": comment,
        "by": DIRECTOR,
        "at": at,
    }


def page(*items: dict[str, Any]) -> dict[str, Any]:
    return {"items": list(items), "next_cursor": None}


def rework(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [i for i in body["items"] if i["kind"] == "rework_document"]


async def test_author_sees_the_returned_document_as_a_rework_row(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["returned"] = page(item())
    fb.cards[DOC_ID] = card(DOC_ID, returned("Добавьте смету расходов."))
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200
    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "ok", "eds": "ok"}
    (row,) = rework(body)
    assert row["id"] == f"rework:{DOC_ID}"
    assert row["role_id"] == rid("MANAGER")
    assert row["title"] == "Доработать: СЗ-2026/028 · Командировка в Самарканд"
    assert row["subtitle"].startswith("Вернул Рустам Директоров: Добавьте смету расходов.")
    assert row["due_label"] == "today"  # «нужно до» не задан — срочное, сегодня
    assert row["object"]["kind"] == "memo"
    assert row["object"]["number"] == "СЗ-2026/028"
    assert row["object"]["path"] == f"/eds/new?draft={DOC_ID}"  # форма «Продолжить» D1-5
    # EDS читают под токеном сотрудника, только свои документы и только возвращённые
    listing = fb.eds["returned"].calls.last.request
    assert listing.headers["authorization"] == "Bearer eds-access-1"
    assert listing.url.params["mine"] == "true"
    assert listing.url.params.get_list("status") == ["returned"]
    assert listing.url.params.get_list("kind") == ["memo", "application", "report"]


async def test_the_row_goes_with_the_author_it_is_not_made_up_for_someone_else(
    web: Web, fb: FeedBackends
) -> None:
    """Чужие документы EDS автору не отдаёт (`mine=true`): у сотрудника без возвратов строк нет."""
    fb.state["returned"] = page()
    await web.login(["MANAGER"])

    body = (await web.client.get("/api/v1/queue")).json()

    assert rework(body) == []
    assert fb.eds["returned"].calls.last.request.url.params["mine"] == "true"
    assert fb.calls(fb.eds["card"]) == 0  # карточки нужны только возвращённым


async def test_deadline_of_the_document_gives_the_badge(web: Web, fb: FeedBackends) -> None:
    fb.state["returned"] = page(
        item(due_date="2027-01-16"), item(OTHER_ID, "ЗЯ-2026/012", due_date="2027-01-01")
    )
    fb.cards[DOC_ID] = card(DOC_ID, returned("Уточните сумму."))
    fb.cards[OTHER_ID] = card(OTHER_ID, returned("Нужна дата."), number="ЗЯ-2026/012")
    await web.login(["MANAGER"])

    rows = rework((await web.client.get("/api/v1/queue")).json())

    by_number = {r["object"]["number"]: r for r in rows}
    assert by_number["СЗ-2026/028"]["due_label"] == "tomorrow"
    assert by_number["СЗ-2026/028"]["due_at"] == "2027-01-16T18:59:59Z"
    assert by_number["ЗЯ-2026/012"]["due_label"] == "overdue"
    assert rows[0]["object"]["number"] == "ЗЯ-2026/012"  # просроченное — выше


async def test_the_latest_return_is_shown_when_the_document_went_around_twice(
    web: Web, fb: FeedBackends
) -> None:
    fb.state["returned"] = page(item())
    fb.cards[DOC_ID] = card(
        DOC_ID,
        returned("Старое замечание.", "2027-01-05T04:00:00Z"),
        returned("Теперь укажите срок.", "2027-01-14T04:00:00Z", round_=2),
    )
    await web.login(["MANAGER"])

    (row,) = rework((await web.client.get("/api/v1/queue")).json())

    assert "Теперь укажите срок." in row["subtitle"]
    assert "Старое замечание." not in row["subtitle"]


async def test_card_failure_keeps_the_row_without_the_remark(web: Web, fb: FeedBackends) -> None:
    fb.state["returned"] = page(item())  # карточки нет: EDS ответит 404
    await web.login(["MANAGER"])

    body = (await web.client.get("/api/v1/queue")).json()

    (row,) = rework(body)
    assert row["subtitle"].startswith("Возвращён на доработку")
    assert body["sources"]["eds"] == "ok"


async def test_card_503_keeps_the_row_and_the_source_ok(web: Web, fb: FeedBackends) -> None:
    """Список пришёл — строки показаны; сбой карточки (подробности) не делает EDS «недоступным»."""
    fb.state["returned"] = page(item(), item(OTHER_ID, "ЗЯ-2026/012"))
    fb.eds["card"].mock(return_value=httpx.Response(503, json={"detail": "down"}))
    await web.login(["MANAGER"])

    body = (await web.client.get("/api/v1/queue")).json()

    assert body["sources"] == {"crm": "ok", "erp": "ok", "eds": "ok"}
    assert [r["subtitle"] for r in rework(body)] == ["Возвращён на доработку"] * 2


async def test_slow_cards_do_not_hold_the_queue(
    web: Web, fb: FeedBackends, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Общий бюджет на карточки: по его исходу — строки без комментария, а не ожидание EDS."""
    monkeypatch.setattr(rework_module, "CARDS_BUDGET", 0.1)

    async def slow(_request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(2)
        return httpx.Response(200, json=card(DOC_ID, returned("Не успела.")))

    fb.state["returned"] = page(item())
    fb.eds["card"].mock(side_effect=slow)
    await web.login(["MANAGER"])

    started = time.monotonic()
    body = (await web.client.get("/api/v1/queue")).json()

    assert time.monotonic() - started < 1.5
    (row,) = rework(body)
    assert row["subtitle"].startswith("Возвращён на доработку")
    assert body["sources"]["eds"] == "ok"


async def test_submit_drops_the_cached_returns(web: Web, fb: FeedBackends) -> None:
    """Автор отправил документ — кэш списка возвратов сброшен: строки нет сразу, а не через 8 с."""
    eds = EdsFake(web.be)  # PATCH и submit; чтение возвратов отвечает FeedBackends
    eds.issued.append("eds-access-1")
    fb.state["returned"] = page(item())
    fb.cards[DOC_ID] = card(DOC_ID, returned("Добавьте смету."))
    await web.login(["MANAGER"])
    assert len(rework((await web.client.get("/api/v1/queue")).json())) == 1

    fb.state["returned"] = (
        page()
    )  # EDS уже не считает документ возвращённым, но кэш ещё держит строку
    assert len(rework((await web.client.get("/api/v1/queue")).json())) == 1
    response = await web.send(
        "PUT",
        f"/api/v1/eds/documents/{DOC_ID}",
        json={"subject": "Командировка в Самарканд", "text": "Смета приложена.", "submit": True},
    )

    assert response.status_code == 200, response.text
    assert rework((await web.client.get("/api/v1/queue")).json()) == []


async def test_eds_down_keeps_the_rest_of_the_queue_and_marks_the_source(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.eds_down = httpx.ConnectError("down")
    fb.state["inbox"] = {
        "escalations": [lead(2041, "ООО «Демо-Депо»", escalation=escalation())],
        "mine": [],
        "unassigned": [],
    }
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200
    check(response, "/queue", "get")
    body = response.json()
    assert body["sources"] == {"crm": "ok", "erp": "ok", "eds": "unavailable"}
    assert [i["kind"] for i in body["items"]] == ["take_lead"]


async def test_eds_refusal_is_not_a_failure_of_the_queue(web: Web, fb: FeedBackends) -> None:
    """EDS не пустил сотрудника по его токену (не заведён) — документов EDS у него нет."""
    fb.eds_exchange_status = 403
    await web.login(["MANAGER"])

    response = await web.client.get("/api/v1/queue")

    assert response.status_code == 200
    assert rework(response.json()) == []


async def test_without_the_section_eds_is_not_called(web: Web, fb: FeedBackends) -> None:
    only_leads = custom(61, "Только лиды", {"dashboard.queue": "full", "crm.leads": "full"})
    fb.state["returned"] = page(item())
    await web.login([only_leads])

    body = (await web.client.get("/api/v1/queue")).json()

    assert rework(body) == []
    assert "eds" not in body["sources"]
    assert fb.calls(fb.eds["returned"]) == 0
    assert fb.calls(fb.eds_exchange) == 0


async def test_rework_rows_count_in_the_queue_badge(web: Web, fb: FeedBackends) -> None:
    fb.state["returned"] = page(item())
    fb.cards[DOC_ID] = card(DOC_ID, returned("Добавьте смету."))
    await web.login(["MANAGER"])

    counters = (await web.client.get("/api/v1/menu-counters")).json()

    queue = next(c for c in counters["items"] if c["section"] == "queue")
    assert (queue["count"], queue["attention"]) == (1, True)


async def test_resubmitted_document_leaves_the_queue(web: Web, fb: FeedBackends) -> None:
    """Автор отправил документ снова — EDS больше не возвращает его: строка исчезает."""
    fb.state["returned"] = page(item())
    fb.cards[DOC_ID] = card(DOC_ID, returned("Добавьте смету."))
    await web.login(["MANAGER"])
    assert len(rework((await web.client.get("/api/v1/queue")).json())) == 1

    fb.state["returned"] = page()
    web.clock.advance(60)  # кэш снимка живёт секунды

    assert rework((await web.client.get("/api/v1/queue")).json()) == []


async def test_return_decision_hints_the_queue(web: Web, monkeypatch: pytest.MonkeyPatch) -> None:
    """Подсказка потока: решение по документу (`approval.decided`) обновляет очередь автора."""
    monkeypatch.setenv("RT_BUS_SECRET_EDS_PLATFORM_BFF", EDS_SECRET)
    headers, raw = delivery(envelope("eds", "approval.decided"), publisher="eds", secret=EDS_SECRET)

    response = await web.client.post("/bus/v1/events", content=raw, headers=headers)

    assert (response.status_code, response.json()["status"]) == (200, "processed")
    hints = [json.loads(m) for ch, m in web.redis.published if ch == CHANNEL]
    assert hints == [
        {
            "topics": ["notifications", "counters", "queue"],
            "reason": "uz.railtech.eds.approval.decided.v1",
        }
    ]

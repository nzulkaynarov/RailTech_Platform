"""«Что ждёт вас» (ГЛ-1): у строки есть «почему это у вас» из факта источника, группа срока (только
из срока, без выдуманного «сегодня»), вид работы и глагол кнопки; «показаны не все»; «Вы ждёте
других» (EDS `GET /waiting`) и «Напомнить» с лимитом в час. Часы тестов — 2027-01-15 13:00."""

from typing import Any

import pytest

from tests.conftest import ContractChecker, Web
from tests.feeds_support import FeedBackends, Moments, escalation, lead
from tests.test_feeds_eds import letter_row, page, route
from tests.test_queue_sign_deputy import (
    DOC,
    MADINA,
    SIGN_ROUTE,
    letter_tasks,
    signature,
    signing_route,
)

LETTER = {
    "id": "40000000-0000-4000-8000-000000000112",
    "number": "ВХ-112/26",
    "subject": "Требование ГНК",
    "sender_name": "ГНК",
    "urgent": False,
}


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


def instruction(entry_id: str, due: str, **over: Any) -> dict[str, Any]:
    return {
        "id": entry_id,
        "letter": LETTER,
        "kind": "execute",
        "role": "responsible",
        "due": due,
        "overdue": False,
        "extension_pending": False,
        "acting_for": None,
        "created_at": "2027-01-11T04:00:00Z",
        **over,
    }


async def rows(web: Web) -> dict[str, dict[str, Any]]:
    response = await web.client.get("/api/v1/queue")
    assert response.status_code == 200, response.text
    return {i["id"]: i for i in response.json()["items"]}


async def test_group_comes_from_the_real_due_date_and_never_from_the_kind(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    """Просрочено — признак EDS; сегодня и позже — срок; подпись без срока — позже."""
    fb.state["letter_tasks"] = letter_tasks(
        instructions=[
            instruction("a0000000-0000-4000-8000-000000000001", "2027-01-13", overdue=True),
            instruction("a0000000-0000-4000-8000-000000000002", "2027-01-15"),
            instruction("a0000000-0000-4000-8000-000000000003", "2027-01-25"),
        ],
        signatures=[signature()],
    )
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    items = {i["id"]: i for i in response.json()["items"]}
    assert items["instruction:a0000000-0000-4000-8000-000000000001"]["group"] == "overdue"
    assert items["instruction:a0000000-0000-4000-8000-000000000002"]["group"] == "today"
    assert items["instruction:a0000000-0000-4000-8000-000000000003"]["group"] == "later"
    # у подписи письма срока нет: была «всегда сегодня», теперь «позже», возраст — в причине
    assert items[f"sign_document:{DOC}"]["group"] == "later"
    assert items[f"sign_document:{DOC}"]["due_label"] == "later"


async def test_extension_group_follows_the_current_instruction_deadline(
    web: Web, fb: FeedBackends
) -> None:
    def extension(ext_id: str, old_due: str) -> dict[str, Any]:
        return {
            "id": ext_id,
            "instruction_id": "60000000-0000-4000-8000-000000000002",
            "letter": LETTER,
            "executor": {"crm_user_id": 7, "full_name": "Иван Исполнитель"},
            "old_due": old_due,
            "new_due": "2027-02-01",
            "reason": "Ждём выписку",
            "acting_for": None,
            "requested_at": "2027-01-14T04:00:00Z",
        }

    fb.state["letter_tasks"] = letter_tasks(
        extensions=[
            extension("b0000000-0000-4000-8000-000000000001", "2027-01-15"),
            extension("b0000000-0000-4000-8000-000000000002", "2027-01-30"),
        ]
    )
    await web.login(["DIRECTOR"])

    items = await rows(web)

    assert items["instruction_extension:b0000000-0000-4000-8000-000000000001"]["group"] == "today"
    later = items["instruction_extension:b0000000-0000-4000-8000-000000000002"]
    assert later["group"] == "later"
    assert later["due_at"].startswith("2027-01-30")
    assert "Иван Исполнитель просит перенос" in later["reason"]


async def test_every_row_says_why_it_is_yours_from_its_own_fact(web: Web, fb: FeedBackends) -> None:
    visa = signing_route(
        "invoice",
        "INV-2026-031",
        id="80000000-0000-4000-8000-000000000082",
        current_step={
            "index": 1,
            "label": "Виза бухгалтера",
            "status": "current",
            "assignee": {"crm_user_id": None, "permission": "approvals.visa_finance"},
        },
    )
    fb.state["letter_tasks"] = letter_tasks(
        instructions=[
            instruction("a0000000-0000-4000-8000-000000000001", "2027-01-25"),
            instruction(
                "a0000000-0000-4000-8000-000000000002",
                "2027-01-25",
                kind="reply",
                role="co_executor",
            ),
        ],
        acquaintances=[{"letter": LETTER, "created_at": "2027-01-14T04:00:00Z"}],
        signatures=[signature(requested_at=fb.m.ago(hours=2))],
    )
    fb.state["signing"] = page(signing_route(created_at=fb.m.ago(days=1, hours=2)), visa)
    fb.state["memos"] = page(route("СЗ-2026/031", step="Директор"))
    await web.login(["DIRECTOR"])

    items = await rows(web)

    first = items["instruction:a0000000-0000-4000-8000-000000000001"]
    assert first["reason"] == "резолюция от 11.01 · вы ответственный"
    second = items["instruction:a0000000-0000-4000-8000-000000000002"]
    assert second["reason"] == "резолюция от 11.01 · вы соисполнитель"
    assert (second["action_label"], second["category"]) == ("Подготовить ответ", "instruction")
    assert items["acquaint:" + str(LETTER["id"])]["reason"].startswith("вас просят ознакомиться")
    assert items["acquaint:" + str(LETTER["id"])]["action_label"] == "Ознакомлен"
    letter_sign = items[f"sign_document:{DOC}"]
    assert letter_sign["reason"] == (
        "вы подписант по реестру полномочий · передано: Иван Исполнитель · ждёт 2 ч"
    )
    contract = items[f"sign_document:{SIGN_ROUTE}"]
    assert contract["reason"] == "вы подписант по реестру полномочий · ждёт 1 д"
    assert contract["category"] == "sign"
    accountant = items["sign_document:80000000-0000-4000-8000-000000000082"]
    assert accountant["reason"].startswith("ваша виза: финансы")
    assert (accountant["category"], accountant["action_label"]) == ("approve", "Завизировать")
    memo = items["memo:50000000-0000-4000-8000-000000000031"]
    assert memo["reason"] == "ваш шаг маршрута: Директор"
    assert (memo["category"], memo["action_label"]) == ("approve", "Согласовать")


async def test_deputy_row_starts_with_whose_work_it_is(web: Web, fb: FeedBackends) -> None:
    fb.state["covering"] = [
        {
            "user_id": 12,
            "full_name": "Мадина Р.",
            "date_from": "2027-01-10",
            "date_to": "2027-01-20",
        }
    ]
    fb.state["letter_tasks"] = letter_tasks(signatures=[signature(acting_for=MADINA)])
    await web.login(["DIRECTOR"])

    items = await rows(web)

    reason = items[f"sign_document:{DOC}:for:12"]["reason"]
    assert reason.startswith("вы замещаете Мадина Р. · вы подписант по реестру полномочий")


async def test_lead_rows_say_whose_client_and_quick_actions_have_verbs(
    web: Web, fb: FeedBackends
) -> None:
    fb.state["inbox"] = {
        "escalations": [
            lead(1, "Демо-Рейл", escalation=escalation(reason="клиент просит звонок")),
        ],
        "mine": [lead(2, "Тест-Сервис", unread=True, last_msg=fb.m.ago(minutes=40))],
        "unassigned": [],
    }
    await web.login(["MANAGER"])

    items = await rows(web)

    take = items["lead:1:take_lead"]
    assert (take["action_label"], take["category"]) == ("Взять", "lead")
    assert take["reason"] == "лид без менеджера · клиент просит звонок"
    answer = items["lead:2:answer_lead"]
    assert (answer["action_label"], answer["reason"]) == ("Ответить", "ваш клиент ждёт ответа")


async def test_queue_says_when_a_source_returned_not_everything(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["letters"] = {**page(letter_row()), "next_cursor": "c2"}
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue")

    check(response, "/queue", "get")
    assert response.json()["truncated"] is True


async def test_complete_queue_has_no_truncated_flag(web: Web, fb: FeedBackends) -> None:
    fb.state["letters"] = page(letter_row())
    await web.login(["DIRECTOR"])

    body = (await web.client.get("/api/v1/queue")).json()

    assert "truncated" not in body


# --- «Вы ждёте других» ---------------------------------------------------------------------------

SIGN_WAIT = "c0000000-0000-4000-8000-000000000001"
ROUTE_WAIT = "c0000000-0000-4000-8000-000000000002"
INSTR_WAIT = "c0000000-0000-4000-8000-000000000003"


def waiting_state(fb: FeedBackends) -> dict[str, Any]:
    return {
        "items": [
            {
                "kind": "letter_signature",
                "object_id": SIGN_WAIT,
                "number": None,
                "title": "Ответ на требование",
                "waiting_on": {"crm_user_id": 4, "full_name": "Рустам Каримов"},
                "waiting_label": None,
                "since": fb.m.ago(hours=3),
                "due": None,
                "remind_available_at": None,
                "remindable": True,
            },
            {
                "kind": "approval",
                "object_id": ROUTE_WAIT,
                "number": "СЗ-2026/212",
                "title": "Закупка кофе",
                "waiting_on": None,
                "waiting_label": "Бухгалтер",
                "since": fb.m.ago(days=1),
                "due": None,
                "remind_available_at": fb.m.ahead(minutes=30),
                "remindable": False,
            },
            {
                "kind": "instruction",
                "object_id": INSTR_WAIT,
                "number": "ВХ-112/26",
                "title": "Требование ГНК",
                "waiting_on": {"crm_user_id": 7, "full_name": "Иван Исполнитель"},
                "waiting_label": None,
                "since": fb.m.ago(days=2),
                "due": "2027-01-20",
                "remind_available_at": None,
                "remindable": True,
            },
        ],
        "more": False,
    }


async def test_waiting_rows_name_who_and_since_when_and_open_the_object(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["waiting"] = waiting_state(fb)
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/queue/waiting")

    check(response, "/queue/waiting", "get")
    by_kind = {i["kind"]: i for i in response.json()["items"]}
    letter = by_kind["letter_signature"]
    assert letter["waiting_on"] == {"id": "4", "name": "Рустам Каримов"}
    assert letter["object"]["path"] == f"/eds/documents?scope=all&doc={SIGN_WAIT}&panel=open"
    assert letter["remindable"] is True
    assert "remind_available_at" not in letter
    memo = by_kind["approval"]
    assert (memo["waiting_label"], memo["remindable"]) == ("Бухгалтер", False)
    assert memo["title"] == "СЗ-2026/212 · Закупка кофе"
    assert memo["object"]["path"].startswith("/eds/approvals/")
    assert memo["remind_available_at"] is not None
    given = by_kind["instruction"]
    assert given["object"]["path"].startswith("/eds/inbox/")
    assert given["due_at"].startswith("2027-01-20")
    assert "truncated" not in response.json()


async def test_waiting_is_empty_and_marked_when_eds_does_not_answer(
    web: Web, fb: FeedBackends
) -> None:
    fb.eds_down = 503
    await web.login(["DIRECTOR"])

    body = (await web.client.get("/api/v1/queue/waiting")).json()

    assert body["items"] == []
    assert body["sources"]["eds"] == "unavailable"


async def test_remind_goes_to_eds_and_the_rate_limit_is_explained(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])

    done = await web.send("POST", f"/api/v1/queue/waiting/letter_signature/{SIGN_WAIT}/remind")

    check(done, "/queue/waiting/{kind}/{id}/remind", "post")
    assert done.json() == {"reminded_at": "2027-01-14T09:00:00Z"}
    assert fb.remind.calls.last.request.url.path.endswith(
        f"/waiting/letter_signature/{SIGN_WAIT}/remind"
    )

    fb.remind_reply = (
        429,
        {
            "code": "RATE_LIMITED",
            "message": "Напоминание уже отправлено.",
            "source": "eds",
            "details": {"retry_after_seconds": 1800},
        },
    )
    again = await web.send("POST", f"/api/v1/queue/waiting/approval/{ROUTE_WAIT}/remind")

    check(again, "/queue/waiting/{kind}/{id}/remind", "post")
    assert again.status_code == 429
    assert again.json()["code"] == "TOO_MANY_REQUESTS"
    assert again.json()["details"]["reason"] == "remind_rate_limited"
    assert again.headers["retry-after"] == "1800"


async def test_rows_without_a_due_date_are_later_not_today(web: Web, fb: FeedBackends) -> None:
    """Свободный лид и непрочитанный «мой» без SLA, заказ и приёмка без срока: группа «позже»."""
    fb.state["inbox"] = {
        "escalations": [lead(2099, "Без SLA", escalation=escalation())],
        "mine": [lead(2098, "Мой", unread=True, last_msg=fb.m.ago(minutes=5))],
        "unassigned": [],
    }
    await web.login(["MANAGER"])

    items = await rows(web)

    for key in ("lead:2099:take_lead", "lead:2098:answer_lead"):
        assert (items[key]["group"], items[key]["due_label"]) == ("later", "later"), key


async def test_deputy_lead_row_names_the_colleague_not_your_client(
    web: Web, fb: FeedBackends
) -> None:
    fb.state["covering"] = [
        {
            "user_id": 12,
            "full_name": "Мадина Р.",
            "date_from": "2026-10-20",
            "date_to": "2027-02-02",
        }
    ]
    fb.state["covered_inbox"] = {
        12: {
            "escalations": [],
            "mine": [lead(2060, "Ждёт Мадину", unread=True, last_msg=fb.m.ago(hours=3))],
            "unassigned": [],
        }
    }
    await web.login(["MANAGER"])

    items = await rows(web)

    (row,) = [i for i in items.values() if "on_behalf_of" in i]
    assert row["reason"].startswith("вы замещаете Мадина Р.")
    assert "ваш клиент" not in row["reason"]


async def test_queue_rows_and_cards_follow_the_interface_language(
    web: Web, fb: FeedBackends
) -> None:
    """СЦ-7 (N1): строки и карточки «Главной» — на языке `Accept-Language`, по умолчанию русский."""
    fb.state["inbox"] = {
        "escalations": [
            lead(1, "Демо-Рейл", escalation=escalation(reason="клиент просит звонок")),
        ],
        "mine": [lead(2, "Тест-Сервис", unread=True, last_msg=fb.m.ago(minutes=40))],
        "unassigned": [],
    }
    await web.login(["MANAGER"])

    async def queue(language: str | None) -> dict[str, dict[str, Any]]:
        headers = {"Accept-Language": language} if language else {}
        response = await web.client.get("/api/v1/queue", headers=headers)
        assert response.status_code == 200, response.text
        return {i["id"]: i for i in response.json()["items"]}

    ru = await queue(None)
    assert ru["lead:2:answer_lead"]["reason"] == "ваш клиент ждёт ответа"
    assert "мин назад" in ru["lead:2:answer_lead"]["subtitle"]

    uz = await queue("uz-UZ,uz;q=0.9,ru;q=0.5")
    assert uz["lead:2:answer_lead"]["title"].startswith("Lidga javob beriş")
    assert uz["lead:2:answer_lead"]["reason"] == "sizning mijozingiz javob kutmoqda"
    assert uz["lead:2:answer_lead"]["action_label"] == "Javob beriş"
    assert "daq. oldin" in uz["lead:2:answer_lead"]["subtitle"]
    assert uz["lead:1:take_lead"]["reason"].startswith("menejersiz lid")

    en = await queue("en")
    assert en["lead:2:answer_lead"]["reason"] == "your client is waiting for a reply"
    assert "min ago" in en["lead:2:answer_lead"]["subtitle"]

    cards = await web.client.get("/api/v1/queue/cards", headers={"Accept-Language": "uz"})
    labels = {c["label"] for c in cards.json()["cards"]}
    assert "Menejersiz lidlar" in labels
    assert not any("Лиды" in label for label in labels)

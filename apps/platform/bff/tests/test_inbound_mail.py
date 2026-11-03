"""Входящая почта общего ящика (W18A-P2): очередь канцелярии, карточка, действия, вложения в EDS,
регистрация ВХ из письма, приём в «Подключениях». CRM и EDS — на respx, данные вымышленные.
"""

import json
from typing import Any

import httpx
import pytest

from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL
from tests.eds_letters_support import FILE_ID, EdsFake, letter
from tests.feeds_support import FeedBackends, Moments

CRM = f"{CRM_URL}/api/v1/inbound-mail"
PDF = b"%PDF-1.4 act 17"


def assist(**over: Any) -> dict[str, Any]:
    return {
        "status": "done",
        "kind": "supplier_doc",
        "summary": "Поставщик прислал акт",
        "action": "register",
        **over,
    }


def item(**over: Any) -> dict[str, Any]:
    base = {
        "id": 17,
        "status": "new",
        "from_email": "buh@supplier.test",
        "from_name": "ООО Пример Поставка",
        "subject": "Акт сверки за октябрь",
        "received_at": "2026-11-02T05:00:00Z",
        "sent_at": "2026-11-02T04:59:00Z",
        "activity_at": "2026-11-02T05:00:00Z",
        "preview": "Добрый день, направляем акт сверки",
        "attachments_count": 1,
        "assist": assist(),
        "type": {
            "code": "supplier_invoice",
            "name": {"ru": "Счёт поставщика", "uz": "Hisob", "en": "Supplier invoice"},
            "color": "gold",
            "icon": "wallet",
            "default_action": "to_accountant",
            "letter_kind": None,
            "active": True,
            "source": "ai",
        },
        "client": {"id": 42, "name": "ООО Пример Поставка"},
        "lead": None,
        "from_history": False,
        "assignee": None,
        "assigned_at": None,
        "personal": False,
        "thread_reply": False,
        "unread": True,
        "messages_count": 1,
        "eds_waiting": False,
        "result": None,
    }
    return {**base, **over}


def card(**over: Any) -> dict[str, Any]:
    base = {
        **item(),
        "to": [{"email": "info@company.test", "staff": None, "mailbox": True}],
        "cc": [],
        "text": "Добрый день, направляем акт сверки за октябрь.",
        "attachments": [
            {
                "index": 0,
                "name": "акт.pdf",
                "content_type": "application/pdf",
                "size": len(PDF),
                "inline": False,
            }
        ],
        "skipped": [{"name": "macro.exe", "reason": "type"}],
        "too_large": False,
        "inns": ["301234567"],
        "eds_letter_id": None,
        "messages": [
            {
                "id": 17,
                "from_email": "buh@supplier.test",
                "from_name": "ООО Пример Поставка",
                "at": "2026-11-02T04:59:00Z",
                "text": "Добрый день, направляем акт сверки за октябрь.",
                "text_tail": "",
                "html": None,
                "html_remote_images": 0,
                "attachments": [
                    {
                        "index": 0,
                        "name": "акт.pdf",
                        "content_type": "application/pdf",
                        "size": 15,
                        "inline": False,
                    }
                ],
                "new_participant": False,
            }
        ],
        "replies": [],
        "journal": [],
        "reply_all_copy": [],
        "personal_label": "Адресовано лично",
        "reply_to": "buh@supplier.test",
        "reply_options": ["buh@supplier.test"],
    }
    return {**base, **over}


def done(outcome: str, **over: Any) -> dict[str, Any]:
    result = {
        "outcome": outcome,
        "by": {"id": 9, "name": "Делопроизводитель"},
        "at": "2026-11-02T06:00:00Z",
        "letter_number": None,
        "lead": None,
        "reason": None,
        **over,
    }
    return {"status": "done", "result": result}


def page(items: list[dict[str, Any]], *, configured: bool = True) -> dict[str, Any]:
    return {
        "items": items,
        "total": len(items),
        "counts": {
            "new": len(items),
            "history": 0,
            "mine": 0,
            "in_work": 0,
            "done": 0,
            "spam": 0,
            "all": len(items),
            "unread_new": len(items),
        },
        "mailbox": {
            "configured": configured,
            "last_poll_at": None,
            "last_ok_at": None,
            "last_error_kind": None,
            "personal_label": "Адресовано лично",
        },
    }


# --- «Мои задачи» -------------------------------------------------------------------------------


@pytest.fixture
def fb(web: Web) -> FeedBackends:
    return FeedBackends(web.be.router, Moments(web.clock))


async def test_registrar_queue_card_and_counter_show_new_mail(
    web: Web, fb: FeedBackends, check: ContractChecker
) -> None:
    fb.state["crm_mail"] = page([item(received_at=fb.m.ago(minutes=30))])
    await web.login(["REGISTRAR"])

    queue = await web.client.get("/api/v1/queue")
    cards = await web.client.get("/api/v1/queue/cards")
    counters = await web.client.get("/api/v1/menu-counters")

    check(queue, "/queue", "get")
    check(cards, "/queue/cards", "get")
    [row] = [i for i in queue.json()["items"] if i["kind"] == "inbound_mail"]
    assert row["title"] == "Разобрать письмо: Акт сверки за октябрь"
    assert row["subtitle"].startswith("ООО Пример Поставка · Поставщик прислал акт")
    assert row["object"] == {
        "kind": "letter",
        "number": "buh@supplier.test",
        "title": "Акт сверки за октябрь",
        "path": "/eds/mail/17",
    }
    [mail_card] = [c for c in cards.json()["cards"] if c["key"] == "inbound_mail"]
    assert (mail_card["count"], mail_card["path"]) == (1, "/eds/mail")
    # «Мои задачи» — без писем «из истории» (W18A-P2-2): фильтр решает CRM.
    asked = fb.crm["mail"].calls[0].request.url.params
    assert asked["view"] == "tasks", "что строкой «Моих задач», решает CRM"
    assert {"module": "eds", "section": "mail", "count": 1, "attention": True} in counters.json()[
        "items"
    ]


async def test_without_imap_the_card_points_to_the_settings(web: Web, fb: FeedBackends) -> None:
    fb.state["crm_mail"] = page([], configured=False)
    await web.login(["REGISTRAR"])

    cards = (await web.client.get("/api/v1/queue/cards")).json()["cards"]

    [mail_card] = [c for c in cards if c["key"] == "inbound_mail"]
    assert mail_card["hint"] == "Почта не подключена — Настройки · Подключения · Почта"


async def test_manager_without_registration_right_has_no_mail_queue(
    web: Web, fb: FeedBackends
) -> None:
    fb.state["crm_mail"] = page([item()])
    await web.login(["MANAGER_ALL"])

    queue = (await web.client.get("/api/v1/queue")).json()["items"]
    cards = (await web.client.get("/api/v1/queue/cards")).json()["cards"]

    assert [i for i in queue if i["kind"] == "inbound_mail"] == []
    assert [c for c in cards if c["key"] == "inbound_mail"] == []
    assert fb.crm["mail"].called, "свои письма есть у любого сотрудника: CRM отдаёт только их"


# --- карточка и действия ------------------------------------------------------------------------


async def test_list_card_and_attachment(web: Web, be: Backends, check: ContractChecker) -> None:
    be.router.get(CRM).mock(return_value=httpx.Response(200, json=page([item()])))
    be.router.get(f"{CRM}/17").mock(return_value=httpx.Response(200, json=card()))
    be.router.get(f"{CRM}/17/attachments/0").mock(
        return_value=httpx.Response(200, content=PDF, headers={"content-type": "text/html"})
    )
    await web.login(["REGISTRAR"])

    listed = await web.client.get("/api/v1/inbound-mail")
    shown = await web.client.get("/api/v1/inbound-mail/17")
    file = await web.client.get("/api/v1/inbound-mail/17/attachments/0")

    check(listed, "/inbound-mail", "get")
    check(shown, "/inbound-mail/{id}", "get")
    assert listed.json()["items"][0]["type"]["default_action"] == "to_accountant"
    assert listed.json()["items"][0]["client"] == {
        "id": 42,
        "number": "42",
        "name": "ООО Пример Поставка",
    }
    body = shown.json()
    assert body["assist"]["action"] == "register"
    assert body["result"] is None
    assert body["to"][0]["mailbox"] is True
    assert file.status_code == 200
    assert file.content == PDF
    assert file.headers["content-type"] == "application/octet-stream", "тип файла не доверяется"
    assert "attachment" in file.headers["content-disposition"]


async def test_registered_mail_card_links_the_letter(web: Web, be: Backends) -> None:
    be.router.get(f"{CRM}/17").mock(
        return_value=httpx.Response(200, json=card(**done("registered", letter_number="ВХ-12/26")))
    )
    await web.login(["REGISTRAR"])

    body = (await web.client.get("/api/v1/inbound-mail/17")).json()

    assert body["result"]["letter_number"] == "ВХ-12/26"
    assert body["result"]["letter_ref"].startswith("/eds/inbox/%D0%92%D0%A5-12%2F26")


async def test_create_lead_archive_and_conflict(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    lead = be.router.post(f"{CRM}/17/lead").mock(
        return_value=httpx.Response(200, json={"lead_id": 42, "created": True})
    )
    archive = be.router.post(f"{CRM}/18/archive").mock(return_value=httpx.Response(204))
    be.router.post(f"{CRM}/19/lead").mock(
        return_value=httpx.Response(
            409, json={"code": "conflict", "message": "x", "details": {"status": "lead"}}
        )
    )
    await web.login(["REGISTRAR"])
    headers = {CSRF_HEADER: web.csrf}

    made = await web.client.post("/api/v1/inbound-mail/17/lead", headers=headers)
    archived = await web.client.post(
        "/api/v1/inbound-mail/18/archive", json={"reason": " реклама "}, headers=headers
    )
    again = await web.client.post("/api/v1/inbound-mail/19/lead", headers=headers)

    check(made, "/inbound-mail/{id}/lead", "post")
    assert made.json() == {"lead_id": 42, "lead_number": "L-0042", "created": True}
    assert lead.called
    assert archived.status_code == 204
    assert json.loads(archive.calls[0].request.content) == {"reason": "реклама"}
    assert again.status_code == 409
    assert again.json()["message"] == "Письмо уже обработано: обновите очередь."
    short = await web.client.post(
        "/api/v1/inbound-mail/18/archive", json={"reason": "x"}, headers=headers
    )
    assert short.status_code == 422


async def test_reply_without_smtp_says_where_to_set_it_up(web: Web, be: Backends) -> None:
    be.router.post(f"{CRM}/17/reply").mock(
        return_value=httpx.Response(
            409,
            json={"code": "conflict", "message": "x", "details": {"reason": "smtp_not_configured"}},
        )
    )
    await web.login(["REGISTRAR"])

    reply = await web.client.post(
        "/api/v1/inbound-mail/17/reply", json={"text": "Спасибо"}, headers={CSRF_HEADER: web.csrf}
    )

    assert reply.status_code == 409
    assert reply.json()["details"]["reason"] == "smtp_not_configured"
    assert "Настройки · Подключения · Почта" in reply.json()["message"]


# --- «Зарегистрировать ВХ» из письма -----------------------------------------------------------


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    fake = EdsFake(be)
    fake.answer(
        "POST",
        "files",
        httpx.Response(
            201,
            json={
                "id": FILE_ID,
                "name": "акт.pdf",
                "content_type": "application/pdf",
                "size": len(PDF),
                "version": 1,
                "sha256": "a" * 64,
                "uploaded_at": "2026-11-02T05:00:00Z",
                "uploaded_by": {"crm_user_id": 9, "full_name": "Делопроизводитель"},
            },
        ),
    )
    fake.answer("POST", "letters", httpx.Response(201, json=letter(links={})))
    return fake


async def test_mail_attachments_become_eds_files_of_the_clerk(
    web: Web, be: Backends, eds: EdsFake, check: ContractChecker
) -> None:
    be.router.get(f"{CRM}/17").mock(return_value=httpx.Response(200, json=card()))
    be.router.get(f"{CRM}/17/attachments/0").mock(return_value=httpx.Response(200, content=PDF))
    await web.login(["REGISTRAR"])

    copied = await web.client.post(
        "/api/v1/inbound-mail/17/eds-files", headers={CSRF_HEADER: web.csrf}
    )

    check(copied, "/inbound-mail/{id}/eds-files", "post")
    assert copied.json() == [
        {"id": FILE_ID, "name": "акт.pdf", "content_type": "application/pdf", "size": len(PDF)}
    ]
    [upload] = eds.made("POST", "files")
    assert upload.headers["content-type"].startswith("multipart/form-data")
    assert PDF in upload.content
    assert "акт.pdf".encode() in upload.content


IN_WORK_BY_OTHER = {
    "code": "conflict",
    "message": "x",
    "details": {
        "reason": "mail_in_work_by_other",
        "assignee_name": "Иванов",
        "assigned_at": "2026-11-02T05:42:00Z",  # 10:42 по Ташкенту
    },
}

FORM: dict[str, Any] = {
    "kind": "supplier",
    "receipt_method": "email",
    "sender_name": "ООО Пример Поставка",
    "received_at": "2026-11-02",
    "subject": "Акт сверки за октябрь",
    "summary": "Поставщик прислал акт сверки",
    "file_ids": [],
    "source_mail_id": 17,
}


async def test_register_from_mail_passes_the_source_and_allows_no_files(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    mark = be.router.post(f"{CRM}/17/registration").mock(return_value=httpx.Response(204))
    await web.login(["REGISTRAR"])

    response = await web.client.post(
        "/api/v1/eds/letters",
        json=FORM,
        headers={CSRF_HEADER: web.csrf, "Idempotency-Key": "mail-17-form"},
    )

    assert response.status_code == 201, response.text
    [call] = eds.made("POST", "letters")
    body = json.loads(call.content)
    assert body["source"] == {"crm_inbound_mail_id": 17}
    assert body["file_ids"] == []
    assert [json.loads(c.request.content) for c in mark.calls] == [{"state": "start"}]


async def test_register_from_mail_in_work_by_other_is_409_before_eds(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    be.router.post(f"{CRM}/17/registration").mock(
        return_value=httpx.Response(409, json=IN_WORK_BY_OTHER)
    )
    await web.login(["REGISTRAR"])

    response = await web.client.post(
        "/api/v1/eds/letters", json=FORM, headers={CSRF_HEADER: web.csrf}
    )

    assert response.status_code == 409
    body = response.json()
    assert body["details"]["reason"] == "mail_in_work_by_other"
    assert body["message"] == "Письмо уже в работе у Иванов с 10:42."
    assert eds.made("POST", "letters") == [], "второго ВХ нет"


async def test_register_from_handled_mail_is_409_before_eds(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    be.router.post(f"{CRM}/17/registration").mock(
        return_value=httpx.Response(
            409,
            json={"code": "conflict", "message": "x", "details": {"reason": "mail_handled"}},
        )
    )
    await web.login(["REGISTRAR"])

    response = await web.client.post(
        "/api/v1/eds/letters", json=FORM, headers={CSRF_HEADER: web.csrf}
    )

    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "mail_handled"
    assert eds.made("POST", "letters") == []


async def test_eds_refusal_gives_the_mail_back_to_work(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    mark = be.router.post(f"{CRM}/17/registration").mock(return_value=httpx.Response(204))
    eds.answer(
        "POST",
        "letters",
        httpx.Response(422, json={"code": "validation_failed", "message": "x", "details": {}}),
    )
    await web.login(["REGISTRAR"])

    response = await web.client.post(
        "/api/v1/eds/letters", json=FORM, headers={CSRF_HEADER: web.csrf}
    )

    assert response.status_code >= 400
    assert [json.loads(c.request.content)["state"] for c in mark.calls] == ["start", "cancel"]


async def test_register_without_mail_still_needs_a_file(web: Web, eds: EdsFake) -> None:
    await web.login(["REGISTRAR"])
    form = {**FORM, "source_mail_id": None}

    response = await web.client.post(
        "/api/v1/eds/letters", json=form, headers={CSRF_HEADER: web.csrf}
    )

    assert response.status_code == 422


# --- приём в «Подключениях» ---------------------------------------------------------------------

IMAP = {
    "configured": True,
    "host": "imap.mail.test",
    "port": 993,
    "security": "ssl",
    "mailbox": "INBOX",
    "assist_enabled": True,
    "personal_rule": True,
    "personal_label": "Адресовано лично",
    "trusted_auth_servers": ["yandex.ru", "google.com"],
    "username": "info@company.test",
    "password_configured": True,
    "password_last4": "abcd",
    "password_updated_at": "2026-11-02T05:00:00Z",
    "secrets_enabled": True,
    "last_poll_at": "2026-11-02T05:00:00Z",
    "last_ok_at": "2026-11-02T05:00:00Z",
    "last_error_kind": None,
    "last_error": None,
}


async def test_admin_reads_saves_and_checks_imap(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    be.router.get(f"{CRM_URL}/api/v1/integrations/imap").mock(
        return_value=httpx.Response(200, json=IMAP)
    )
    saved = be.router.put(f"{CRM_URL}/api/v1/integrations/imap").mock(
        return_value=httpx.Response(200, json=IMAP)
    )
    be.router.post(f"{CRM_URL}/api/v1/integrations/imap/check").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": False,
                "error_kind": "auth_failed",
                "detail": "LOGIN rejected",
                "messages": None,
                "latency_ms": None,
            },
        )
    )
    await web.login(["ADMIN"])
    headers = {CSRF_HEADER: web.csrf}

    got = await web.client.get("/api/v1/admin/integrations/imap")
    put = await web.client.put(
        "/api/v1/admin/integrations/imap",
        json={
            "host": "imap.mail.test",
            "username": "info@company.test",
            "imap_password": "app-pass-1234",
            "password": "admin-pass",
        },
        headers=headers,
    )
    probe = await web.client.post("/api/v1/admin/integrations/imap/check", headers=headers)

    check(got, "/admin/integrations/imap", "get")
    check(probe, "/admin/integrations/imap/check", "post")
    assert put.status_code == 200, put.text
    sent = json.loads(saved.calls[0].request.content)
    assert sent["imap_password"] == "app-pass-1234"
    assert "app-pass" not in put.text, "пароль приложения в ответ не возвращается"
    assert probe.json()["error_kind"] == "auth_failed"


async def test_registrar_does_not_touch_imap_settings(web: Web) -> None:
    await web.login(["REGISTRAR"])

    assert (await web.client.get("/api/v1/admin/integrations/imap")).status_code == 403


async def test_assist_only_by_button_and_disabled_says_so(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    called = be.router.post(f"{CRM}/17/assist").mock(
        return_value=httpx.Response(200, json=assist(status="done"))
    )
    be.router.post(f"{CRM}/18/assist").mock(
        return_value=httpx.Response(
            409, json={"code": "conflict", "message": "x", "details": {"reason": "assist_disabled"}}
        )
    )
    be.router.get(f"{CRM}/17").mock(
        return_value=httpx.Response(
            200,
            json=card(assist={"status": "none", "kind": None, "summary": None, "action": None}),
        )
    )
    await web.login(["REGISTRAR"])
    headers = {CSRF_HEADER: web.csrf}

    opened = await web.client.get("/api/v1/inbound-mail/17")
    assert opened.json()["assist"]["status"] == "none"
    assert not called.called, "открыть карточку — не звать модель"
    asked = await web.client.post("/api/v1/inbound-mail/17/assist", headers=headers)
    off = await web.client.post("/api/v1/inbound-mail/18/assist", headers=headers)

    check(asked, "/inbound-mail/{id}/assist", "post")
    assert asked.json()["kind"] == "supplier_doc"
    assert off.status_code == 409
    assert off.json()["details"]["reason"] == "assist_disabled"


# --- «Подозрительные» и загрузка за период (W18A-P2-2) -------------------------------------------


async def test_spam_tab_forwards_filters_counts_and_history_mark(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    body = {
        **page([item(status="spam", from_history=True)]),
        "counts": {**page([])["counts"], "new": 4, "history": 2, "spam": 1},
    }
    listed_crm = be.router.get(CRM).mock(return_value=httpx.Response(200, json=body))
    await web.login(["REGISTRAR"])

    listed = await web.client.get("/api/v1/inbound-mail?view=spam&history=true")

    check(listed, "/inbound-mail", "get")
    params = listed_crm.calls[0].request.url.params
    assert (params["view"], params["history"]) == ("spam", "true")
    data = listed.json()
    assert (data["counts"]["new"], data["counts"]["history"], data["counts"]["spam"]) == (4, 2, 1)
    assert (data["items"][0]["status"], data["items"][0]["from_history"]) == ("spam", True)
    plain = await web.client.get("/api/v1/inbound-mail")
    assert "history" not in listed_crm.calls[1].request.url.params
    assert plain.json()["items"][0]["from_history"] is True


async def test_not_spam_and_discard_forward_and_conflict(web: Web, be: Backends) -> None:
    moved = be.router.post(f"{CRM}/17/not-spam").mock(return_value=httpx.Response(204))
    removed = be.router.post(f"{CRM}/18/discard").mock(return_value=httpx.Response(204))
    be.router.post(f"{CRM}/19/discard").mock(
        return_value=httpx.Response(
            409, json={"code": "conflict", "message": "x", "details": {"status": "new"}}
        )
    )
    await web.login(["REGISTRAR"])
    headers = {CSRF_HEADER: web.csrf}

    first = await web.client.post("/api/v1/inbound-mail/17/not-spam", headers=headers)
    second = await web.client.post("/api/v1/inbound-mail/18/discard", headers=headers)
    again = await web.client.post("/api/v1/inbound-mail/19/discard", headers=headers)

    assert (first.status_code, second.status_code) == (204, 204)
    assert moved.called
    assert removed.called
    assert again.status_code == 409
    assert again.json()["message"] == "Письмо уже обработано: обновите очередь."


async def test_manager_cannot_mark_not_spam(web: Web) -> None:
    await web.login(["MANAGER_ALL"])
    response = await web.client.post(
        "/api/v1/inbound-mail/17/not-spam", headers={CSRF_HEADER: web.csrf}
    )
    assert response.status_code == 403


HISTORY = {
    "id": 3,
    "days": 30,
    "status": "running",
    "found": 120,
    "processed": 25,
    "created": 20,
    "limited": False,
    "error_kind": None,
    "started_at": "2026-11-03T05:00:00Z",
    "finished_at": None,
}


async def test_admin_finds_folders_saves_them_and_loads_history(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    status = {
        **IMAP,
        "folders": [
            {"name": "INBOX", "label": "INBOX", "spam": False},
            {"name": "&BCEEPwQwBDw-", "label": "Спам", "spam": True},
        ],
        "history": HISTORY,
    }
    be.router.get(f"{CRM_URL}/api/v1/integrations/imap").mock(
        return_value=httpx.Response(200, json=status)
    )
    saved = be.router.put(f"{CRM_URL}/api/v1/integrations/imap").mock(
        return_value=httpx.Response(200, json=status)
    )
    be.router.post(f"{CRM_URL}/api/v1/integrations/imap/folders").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "folders": [
                    {"name": "INBOX", "label": "INBOX", "junk": False, "selectable": True},
                    {"name": "&BCEEPwQwBDw-", "label": "Спам", "junk": True, "selectable": True},
                ],
                "spam_suggestion": "&BCEEPwQwBDw-",
            },
        )
    )
    started = be.router.post(f"{CRM_URL}/api/v1/integrations/imap/history").mock(
        return_value=httpx.Response(200, json=HISTORY)
    )
    await web.login(["ADMIN"])
    headers = {CSRF_HEADER: web.csrf}

    got = await web.client.get("/api/v1/admin/integrations/imap")
    found = await web.client.post("/api/v1/admin/integrations/imap/folders", headers=headers)
    put = await web.client.put(
        "/api/v1/admin/integrations/imap",
        json={
            "host": "imap.mail.test",
            "folders": [{"name": "INBOX"}, {"name": "&BCEEPwQwBDw-", "spam": True}],
            "password": "admin-pass",
        },
        headers=headers,
    )
    history = await web.client.post(
        "/api/v1/admin/integrations/imap/history", json={"days": 30}, headers=headers
    )
    wrong = await web.client.post(
        "/api/v1/admin/integrations/imap/history", json={"days": 5}, headers=headers
    )

    check(got, "/admin/integrations/imap", "get")
    check(found, "/admin/integrations/imap/folders", "post")
    check(history, "/admin/integrations/imap/history", "post")
    assert got.json()["folders"][1] == {"name": "&BCEEPwQwBDw-", "label": "Спам", "spam": True}
    assert got.json()["history"]["processed"] == 25
    assert found.json()["spam_suggestion"] == "&BCEEPwQwBDw-"
    assert put.status_code == 200, put.text
    assert json.loads(saved.calls[0].request.content)["folders"] == [
        {"name": "INBOX", "spam": False},
        {"name": "&BCEEPwQwBDw-", "spam": True},
    ]
    assert json.loads(started.calls[0].request.content) == {"days": 30}
    assert wrong.status_code == 422
    assert started.call_count == 1


async def test_history_without_settings_says_what_to_do(web: Web, be: Backends) -> None:
    be.router.post(f"{CRM_URL}/api/v1/integrations/imap/history").mock(
        return_value=httpx.Response(
            409, json={"code": "conflict", "message": "x", "details": {"field": "host"}}
        )
    )
    await web.login(["ADMIN"])

    response = await web.client.post(
        "/api/v1/admin/integrations/imap/history",
        json={"days": 7},
        headers={CSRF_HEADER: web.csrf},
    )

    assert response.status_code == 409
    assert response.json()["message"].startswith("Сначала настройте приём почты")


async def test_registrar_cannot_start_history(web: Web) -> None:
    await web.login(["REGISTRAR"])
    response = await web.client.post(
        "/api/v1/admin/integrations/imap/history",
        json={"days": 7},
        headers={CSRF_HEADER: web.csrf},
    )
    assert response.status_code == 403


# --- обращение: «в работе», представления, цепочки (W18A-P2-3) ---------------------------------


async def test_views_search_and_result_of_done_mail(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    rows = [
        item(id=1, **done("registered", letter_number="ВХ-12/26")),
        item(id=2, **done("lead", lead={"id": 42, "name": "Азиз"})),
        item(id=3, **done("archived", reason="рассылка")),
    ]
    listed_crm = be.router.get(CRM).mock(return_value=httpx.Response(200, json=page(rows)))
    await web.login(["REGISTRAR"])

    listed = await web.client.get("/api/v1/inbound-mail?view=done&q= Акт ")

    check(listed, "/inbound-mail", "get")
    params = listed_crm.calls[0].request.url.params
    assert (params["view"], params["q"]) == ("done", "Акт")
    registered, lead, archived = [i["result"] for i in listed.json()["items"]]
    assert registered["letter_number"] == "ВХ-12/26"
    assert registered["letter_ref"].startswith("/eds/inbox/")
    assert lead["lead"] == {"id": 42, "number": "L-0042", "name": "Азиз"}
    assert (archived["outcome"], archived["reason"]) == ("archived", "рассылка")
    assert registered["by"] == {"id": 9, "name": "Делопроизводитель"}


async def test_take_conflict_says_who_since_when_and_takeover_goes_through(
    web: Web, be: Backends
) -> None:
    take = be.router.post(f"{CRM}/17/take").mock(
        side_effect=[
            httpx.Response(409, json=IN_WORK_BY_OTHER),
            httpx.Response(204),
        ]
    )
    await web.login(["REGISTRAR"])
    headers = {CSRF_HEADER: web.csrf}

    busy = await web.client.post("/api/v1/inbound-mail/17/take", json={}, headers=headers)
    forced = await web.client.post(
        "/api/v1/inbound-mail/17/take", json={"takeover": True}, headers=headers
    )

    assert busy.status_code == 409
    body = busy.json()
    assert body["message"] == "Письмо уже в работе у Иванов с 10:42."
    assert (body["details"]["assignee_name"], body["details"]["reason"]) == (
        "Иванов",
        "mail_in_work_by_other",
    )
    assert forced.status_code == 204
    assert [json.loads(c.request.content) for c in take.calls] == [
        {"takeover": False},
        {"takeover": True},
    ]


async def test_release_read_and_bulk_archive(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    release = be.router.post(f"{CRM}/17/release").mock(return_value=httpx.Response(204))
    read = be.router.post(f"{CRM}/17/read").mock(return_value=httpx.Response(204))
    bulk = be.router.post(f"{CRM}/bulk-archive").mock(
        return_value=httpx.Response(
            200,
            json={
                "archived": [1, 2],
                "skipped": [
                    {
                        "id": 3,
                        "reason": "in_work_by_other",
                        "assignee": {"id": 7, "name": "Иванов"},
                    },
                    {"id": 4, "reason": "handled", "assignee": None},
                ],
            },
        )
    )
    await web.login(["REGISTRAR"])
    headers = {CSRF_HEADER: web.csrf}

    back = await web.client.post("/api/v1/inbound-mail/17/release", headers=headers)
    seen = await web.client.post("/api/v1/inbound-mail/17/read", headers=headers)
    many = await web.client.post(
        "/api/v1/inbound-mail/bulk-archive",
        json={"ids": [1, 2, 3, 4], "reason": " рассылки "},
        headers=headers,
    )

    assert (back.status_code, seen.status_code) == (204, 204)
    assert release.called
    assert read.called
    check(many, "/inbound-mail/bulk-archive", "post")
    assert many.json()["skipped"][0] == {
        "id": 3,
        "reason": "in_work_by_other",
        "assignee": {"id": 7, "name": "Иванов"},
    }
    assert json.loads(bulk.calls[0].request.content) == {"ids": [1, 2, 3, 4], "reason": "рассылки"}


async def test_reply_all_and_awaiting_are_forwarded(web: Web, be: Backends) -> None:
    sent = be.router.post(f"{CRM}/17/reply").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 5,
                "to_email": "buh@supplier.test",
                "subject": "Re: Акт",
                "status": "queued",
                "created_at": "2026-11-02T06:00:00Z",
                "sent_at": None,
                "by": {"id": 9, "name": "Делопроизводитель"},
            },
        )
    )
    await web.login(["REGISTRAR"])

    reply = await web.client.post(
        "/api/v1/inbound-mail/17/reply",
        json={"text": "Принято", "reply_all": True, "awaiting": True},
        headers={CSRF_HEADER: web.csrf},
    )

    assert reply.status_code == 200, reply.text
    assert json.loads(sent.calls[0].request.content) == {
        "text": "Принято",
        "to": None,
        "reply_all": True,
        "awaiting": True,
    }


async def test_manager_opens_only_own_mail_and_cannot_use_first_line_actions(
    web: Web, be: Backends
) -> None:
    be.router.get(f"{CRM}/17").mock(
        return_value=httpx.Response(200, json=card(status="in_work", personal=True))
    )
    be.router.get(f"{CRM}/18").mock(
        return_value=httpx.Response(403, json={"code": "forbidden", "message": "x", "details": {}})
    )
    await web.login(["MANAGER_ALL"])
    headers = {CSRF_HEADER: web.csrf}

    own = await web.client.get("/api/v1/inbound-mail/17")
    foreign = await web.client.get("/api/v1/inbound-mail/18")
    lead = await web.client.post("/api/v1/inbound-mail/17/lead", headers=headers)
    take = await web.client.post("/api/v1/inbound-mail/17/take", json={}, headers=headers)
    bulk = await web.client.post(
        "/api/v1/inbound-mail/bulk-archive", json={"ids": [17], "reason": "тест"}, headers=headers
    )

    assert own.status_code == 200
    assert own.json()["personal"] is True
    assert foreign.status_code == 403
    assert (lead.status_code, take.status_code, bulk.status_code) == (403, 403, 403)


async def test_my_tasks_have_own_rows_for_mail_in_work_and_personal(
    web: Web, fb: FeedBackends
) -> None:
    """Сотрудник без раздела канцелярии: CRM отдаёт только его письма — строка ведёт в
    `/eds/my-mail/…`;
    у делопроизводителя «Новое» — разобрать, «в работе» — своя строка."""
    fb.state["crm_mail"] = page(
        [
            item(
                id=31,
                status="in_work",
                personal=True,
                assignee={"id": 9, "name": "Я"},
                assigned_at=fb.m.ago(minutes=5),
            ),
            item(id=32, status="in_work", assignee={"id": 9, "name": "Я"}, thread_reply=True),
            item(id=33, status="new"),
        ]
    )
    await web.login(["MANAGER_ALL"])

    rows = [i for i in (await web.client.get("/api/v1/queue")).json()["items"] if "mail" in i["id"]]

    assert {r["id"] for r in rows} == {"mail:31", "mail:32"}, "«Новое» — только первая линия"
    by_id = {r["id"]: r for r in rows}
    assert by_id["mail:31"]["title"].startswith("Письмо вам лично: ")
    assert by_id["mail:31"]["kind"] == "inbound_mail_mine"
    assert by_id["mail:31"]["object"]["path"] == "/eds/my-mail/31"
    assert by_id["mail:32"]["title"].startswith("Письмо в работе: ")


async def test_registrar_gets_new_and_own_work_rows_with_first_line_paths(
    web: Web, fb: FeedBackends
) -> None:
    fb.state["crm_mail"] = page(
        [
            item(id=41, status="new"),
            item(id=42, status="registering", assignee={"id": 9, "name": "Я"}),
        ]
    )
    await web.login(["REGISTRAR"])

    rows = [i for i in (await web.client.get("/api/v1/queue")).json()["items"] if "mail" in i["id"]]

    assert {(r["id"], r["kind"], r["object"]["path"]) for r in rows} == {
        ("mail:41", "inbound_mail", "/eds/mail/41"),
        ("mail:42", "inbound_mail_mine", "/eds/mail/42"),
    }


HTML_CARD = card(
    messages=[
        {
            **card()["messages"][0],
            "text": "Новинки недели",
            "text_tail": "On Mon, A wrote:\n> старое",
            "html": '<p>Новинки</p><img data-rt-src="https://cdn.example.test/a.png">',
            "html_remote_images": 1,
            "attachments": [
                {
                    "index": 0,
                    "name": "logo.png",
                    "content_type": "image/png",
                    "size": 90,
                    "inline": True,
                }
            ],
        }
    ],
    attachments=[
        {"index": 0, "name": "logo.png", "content_type": "image/png", "size": 90, "inline": True},
        {
            "index": 1,
            "name": "акт.pdf",
            "content_type": "application/pdf",
            "size": len(PDF),
            "inline": False,
        },
    ],
)


async def test_card_passes_html_tail_and_remote_image_count(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    be.router.get(f"{CRM}/17").mock(return_value=httpx.Response(200, json=HTML_CARD))
    await web.login(["REGISTRAR"])

    response = await web.client.get("/api/v1/inbound-mail/17")

    check(response, "/inbound-mail/{id}", "get")
    [message] = response.json()["messages"]
    assert message["html"] == '<p>Новинки</p><img data-rt-src="https://cdn.example.test/a.png">'
    assert (message["text"], message["text_tail"]) == (
        "Новинки недели",
        "On Mon, A wrote:\n> старое",
    )
    assert message["html_remote_images"] == 1
    assert message["attachments"][0]["inline"] is True


async def test_inline_images_are_not_copied_to_the_registered_letter(
    web: Web, be: Backends, eds: EdsFake, check: ContractChecker
) -> None:
    be.router.get(f"{CRM}/17").mock(return_value=httpx.Response(200, json=HTML_CARD))
    asked = be.router.get(f"{CRM}/17/attachments/1").mock(
        return_value=httpx.Response(200, content=PDF)
    )
    logo = be.router.get(f"{CRM}/17/attachments/0").mock(
        return_value=httpx.Response(200, content=b"x")
    )
    await web.login(["REGISTRAR"])

    copied = await web.client.post(
        "/api/v1/inbound-mail/17/eds-files", headers={CSRF_HEADER: web.csrf}
    )

    check(copied, "/inbound-mail/{id}/eds-files", "post")
    assert [f["name"] for f in copied.json()] == ["акт.pdf"]
    assert asked.called
    assert not logo.called, "логотип из тела письма в файлы входящего не попадает"


def _old_crm_card() -> dict[str, Any]:
    """Ответ CRM до P2-4: у сообщений и вложений нет полей показа письма."""
    old = card()
    for message in old["messages"]:
        for field in ("text_tail", "html", "html_remote_images"):
            message.pop(field)
        for file in message["attachments"]:
            file.pop("inline")
    for file in old["attachments"]:
        file.pop("inline")
    return old


async def test_card_from_old_crm_without_display_fields_still_works(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    be.router.get(f"{CRM}/17").mock(return_value=httpx.Response(200, json=_old_crm_card()))
    await web.login(["REGISTRAR"])

    response = await web.client.get("/api/v1/inbound-mail/17")

    check(response, "/inbound-mail/{id}", "get")
    assert response.status_code == 200
    [message] = response.json()["messages"]
    assert (message["text_tail"], message["html"], message["html_remote_images"]) == ("", None, 0)
    assert message["attachments"][0]["inline"] is False
    assert response.json()["attachments"][0]["inline"] is False


async def test_register_while_already_registering_is_409_and_does_not_cancel(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    """Двойное нажатие «Зарегистрировать»: вторая попытка — 409 до EDS, а `cancel` не уходит —
    он сбросил бы регистрацию, которая идёт первым запросом."""
    mark = be.router.post(f"{CRM}/17/registration").mock(
        return_value=httpx.Response(
            409,
            json={"code": "conflict", "message": "x", "details": {"reason": "mail_registering"}},
        )
    )
    await web.login(["REGISTRAR"])

    response = await web.client.post(
        "/api/v1/eds/letters", json=FORM, headers={CSRF_HEADER: web.csrf}
    )

    assert response.status_code == 409
    body = response.json()
    assert body["details"]["reason"] == "mail_registering"
    assert body["message"] == "Письмо уже регистрируется — дождитесь результата."
    assert eds.made("POST", "letters") == [], "второго ВХ нет"
    assert [json.loads(c.request.content)["state"] for c in mark.calls] == ["start"]


async def test_reply_to_choice_and_new_participant_pass_through(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    messages = card()["messages"] + [
        {
            **card()["messages"][0],
            "id": 18,
            "from_email": "evil@spoof.test",
            "new_participant": True,
        }
    ]
    be.router.get(f"{CRM}/17").mock(
        return_value=httpx.Response(
            200,
            json=card(
                messages=messages,
                reply_options=["buh@supplier.test", "evil@spoof.test"],
            ),
        )
    )
    sent = be.router.post(f"{CRM}/17/reply").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": 5,
                "to_email": "buh@supplier.test",
                "subject": "Re: Акт",
                "status": "queued",
                "created_at": "2026-11-02T06:00:00Z",
                "sent_at": None,
                "by": None,
            },
        )
    )
    await web.login(["REGISTRAR"])

    shown = await web.client.get("/api/v1/inbound-mail/17")
    reply = await web.client.post(
        "/api/v1/inbound-mail/17/reply",
        json={"text": "Ответ", "to": "buh@supplier.test"},
        headers={CSRF_HEADER: web.csrf},
    )

    check(shown, "/inbound-mail/{id}", "get")
    body = shown.json()
    assert [m["new_participant"] for m in body["messages"]] == [False, True]
    assert (body["reply_to"], body["reply_options"]) == (
        "buh@supplier.test",
        ["buh@supplier.test", "evil@spoof.test"],
    )
    assert reply.status_code == 200, reply.text
    assert json.loads(sent.calls[0].request.content)["to"] == "buh@supplier.test"


async def test_repeat_registration_after_waiting_returns_the_same_letter_not_a_second(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    """Регистрация зависла («ждёт подтверждения»), сотрудник нажал снова: CRM разрешает повтор,
    EDS отвечает 200 с тем
    же ВХ (одно письмо ящика — один ВХ) — экран получает ту же карточку, второго ВХ нет."""
    be.router.post(f"{CRM}/17/registration").mock(return_value=httpx.Response(204))
    await web.login(["REGISTRAR"])
    headers = {CSRF_HEADER: web.csrf}

    first = await web.client.post(
        "/api/v1/eds/letters", json=FORM, headers={**headers, "Idempotency-Key": "mail-17-first"}
    )
    eds.answer("POST", "letters", httpx.Response(200, json=letter(links={})))
    again = await web.client.post(
        "/api/v1/eds/letters", json=FORM, headers={**headers, "Idempotency-Key": "mail-17-again"}
    )

    assert (first.status_code, again.status_code) == (201, 201), again.text
    assert again.json()["id"] == first.json()["id"]
    assert again.json()["number"] == first.json()["number"]
    sent = [json.loads(c.content)["source"] for c in eds.made("POST", "letters")]
    assert sent == [{"crm_inbound_mail_id": 17}] * 2

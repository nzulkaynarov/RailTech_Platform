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
        "preview": "Добрый день, направляем акт сверки",
        "attachments_count": 1,
        "assist": assist(),
        "client": {"id": 42, "name": "ООО Пример Поставка"},
        "lead": None,
    }
    return {**base, **over}


def card(**over: Any) -> dict[str, Any]:
    base = {
        **item(),
        "to": ["info@company.test"],
        "text": "Добрый день, направляем акт сверки за октябрь.",
        "attachments": [
            {"index": 0, "name": "акт.pdf", "content_type": "application/pdf", "size": len(PDF)}
        ],
        "skipped": [{"name": "macro.exe", "reason": "type"}],
        "too_large": False,
        "inns": ["301234567"],
        "eds_letter_id": None,
        "eds_letter_number": None,
        "result_lead": None,
        "archive_reason": None,
        "handled_at": None,
        "handled_by": None,
        "replies": [],
    }
    return {**base, **over}


def page(items: list[dict[str, Any]], *, configured: bool = True) -> dict[str, Any]:
    return {
        "items": items,
        "total": len(items),
        "counts": {"new": len(items), "history": 0, "spam": 0},
        "mailbox": {
            "configured": configured,
            "last_poll_at": None,
            "last_ok_at": None,
            "last_error_kind": None,
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
    assert (asked["status"], asked["history"]) == ("new", "false")
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
    assert not fb.crm["mail"].called, "без раздела канцелярии CRM не спрашиваем"
    assert (await web.client.get("/api/v1/inbound-mail")).status_code == 403


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
    assert listed.json()["items"][0]["client"] == {
        "id": 42,
        "number": "42",
        "name": "ООО Пример Поставка",
    }
    body = shown.json()
    assert body["assist"]["action"] == "register"
    assert (body["letter_number"], body["letter_ref"]) == (None, None)
    assert file.status_code == 200
    assert file.content == PDF
    assert file.headers["content-type"] == "application/octet-stream", "тип файла не доверяется"
    assert "attachment" in file.headers["content-disposition"]


async def test_registered_mail_card_links_the_letter(web: Web, be: Backends) -> None:
    be.router.get(f"{CRM}/17").mock(
        return_value=httpx.Response(
            200, json=card(status="registered", eds_letter_number="ВХ-12/26")
        )
    )
    await web.login(["REGISTRAR"])

    body = (await web.client.get("/api/v1/inbound-mail/17")).json()

    assert body["letter_ref"].startswith("/eds/inbox/%D0%92%D0%A5-12%2F26")


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
    be.router.get(f"{CRM}/17").mock(return_value=httpx.Response(200, json=card()))
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


async def test_register_from_already_handled_mail_is_409_before_eds(
    web: Web, be: Backends, eds: EdsFake
) -> None:
    be.router.get(f"{CRM}/17").mock(return_value=httpx.Response(200, json=card(status="lead")))
    await web.login(["REGISTRAR"])

    response = await web.client.post(
        "/api/v1/eds/letters", json=FORM, headers={CSRF_HEADER: web.csrf}
    )

    assert response.status_code == 409
    assert response.json()["details"]["reason"] == "mail_handled"
    assert eds.made("POST", "letters") == []


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
        "counts": {"new": 4, "history": 2, "spam": 1},
    }
    listed_crm = be.router.get(CRM).mock(return_value=httpx.Response(200, json=body))
    await web.login(["REGISTRAR"])

    listed = await web.client.get("/api/v1/inbound-mail?status=spam&history=true")

    check(listed, "/inbound-mail", "get")
    params = listed_crm.calls[0].request.url.params
    assert (params["status"], params["history"]) == ("spam", "true")
    data = listed.json()
    assert data["counts"] == {"new": 4, "history": 2, "spam": 1}
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

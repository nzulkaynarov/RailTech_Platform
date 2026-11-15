"""«Почта · Отправленные» (план 2.8, MAIL-1): BFF отдаёт журнал CRM и ссылку на документ EDS."""

import httpx

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import CRM_URL

DOC_ID = "70000000-0000-4000-8000-000000000014"


async def test_sent_mail_page_and_body(web: Web, be: Backends, check: ContractChecker) -> None:
    item = {
        "id": 5,
        "to_email": "gni@example.uz",
        "subject": "Ответ на требование",
        "status": "sent",
        "error": None,
        "lang": "ru",
        "source": "eds",
        "purpose": "eds_letter",
        "ref_kind": "document",
        "ref_id": DOC_ID,
        "attachments": 1,
        "resendable": True,
        "requested_by": 7,
        "requested_by_name": "Демо Делопроизводителев",
        "created_at": "2026-11-15T09:00:00Z",
        "sent_at": "2026-11-15T09:00:05Z",
    }
    listed = be.router.get(f"{CRM_URL}/api/v1/mail/sent").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [item, {**item, "id": 6, "source": "erp", "ref_kind": "quote"}],
                "next_cursor": "c1",
            },
        )
    )
    be.router.get(f"{CRM_URL}/api/v1/mail/sent/5").mock(
        return_value=httpx.Response(
            200, json={"id": 5, "text": "Направляем пояснения.", "attachments": ["letter.pdf"]}
        )
    )
    be.router.get(f"{CRM_URL}/api/v1/mail/sent/9").mock(
        return_value=httpx.Response(404, json={"code": "not_found", "message": "email not found"})
    )
    assert (await web.login(["REGISTRAR"])).status_code == 200

    page = await web.client.get("/api/v1/mail/sent", params={"q": " требование ", "status": "sent"})
    check(page, "/mail/sent", "get")
    assert dict(listed.calls.last.request.url.params) == {
        "limit": "50",
        "q": "требование",
        "status": "sent",
    }
    rows = page.json()["items"]
    assert rows[0]["path"] == f"/eds/documents?scope=all&doc={DOC_ID}&panel=open"
    assert rows[1]["path"] is None
    assert (rows[0]["to"], rows[0]["requested_by"]) == ("gni@example.uz", "Демо Делопроизводителев")

    body = await web.client.get("/api/v1/mail/sent/5")
    check(body, "/mail/sent/{id}", "get")
    assert body.json() == {
        "id": "5",
        "text": "Направляем пояснения.",
        "attachments": ["letter.pdf"],
    }
    assert (await web.client.get("/api/v1/mail/sent/9")).status_code == 404


async def test_resend_creates_a_new_journal_row(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    """MAIL-2: «Отправить ещё раз» — новая строка журнала CRM; нельзя — 409 CRM как есть."""
    resent = be.router.post(f"{CRM_URL}/api/v1/mail/sent/5/resend").mock(
        return_value=httpx.Response(
            201,
            json={
                "id": 12,
                "to_email": "gni@example.uz",
                "subject": "Ответ на требование",
                "status": "queued",
                "error": None,
                "lang": "ru",
                "source": "eds",
                "purpose": "eds_letter",
                "ref_kind": "document",
                "ref_id": DOC_ID,
                "attachments": 1,
                "resendable": False,
                "requested_by": 7,
                "requested_by_name": "Демо Делопроизводителев",
                "created_at": "2026-11-15T10:00:00Z",
                "sent_at": None,
            },
        )
    )
    be.router.post(f"{CRM_URL}/api/v1/mail/sent/6/resend").mock(
        return_value=httpx.Response(
            409,
            json={
                "code": "conflict",
                "message": "mail cannot be resent",
                "details": {"reason": "mail_not_resendable"},
            },
        )
    )
    assert (await web.login(["REGISTRAR"])).status_code == 200

    created = await web.send("POST", "/api/v1/mail/sent/5/resend")
    check(created, "/mail/sent/{id}/resend", "post")
    assert resent.called
    assert (created.status_code, created.json()["id"], created.json()["status"]) == (
        201,
        "12",
        "queued",
    )
    refused = await web.send("POST", "/api/v1/mail/sent/6/resend")
    assert refused.status_code == 409
    assert refused.json()["details"]["reason"] == "mail_not_resendable"

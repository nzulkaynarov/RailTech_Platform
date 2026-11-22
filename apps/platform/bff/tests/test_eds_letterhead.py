"""EDS · Письмо на бланке (P4 волны 18a): прокси BFF к EDS — тело блоками и отправка адресату,
PDF фонового рендера
(состояние и поток `application/pdf`), передача на регистрацию (B-P8B-4), повтор отправки,
бланк компании.

EDS — на respx (`eds_documents_support`); ответы BFF сверяются со схемами platform-bff.yaml.
Решения (права, кэш PDF,
номера, почта) — за EDS; здесь — разделы каталога до EDS, поля запроса, флаги карточки и формат
ответов.
"""

from typing import Any

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.eds_documents_support import DOC_ID, EARLIER, ME, NOW, EdsFake, document

BASE = "/api/v1/eds"
BODY: dict[str, Any] = {
    "version": 1,
    "lang": "ru",
    "doc": {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Ответ."}]}],
    },
}
LETTER_FORM: dict[str, Any] = {
    "kind": "letter_out",
    "subject": "Ответ на требование",
    "text": "Ответ.",
    "recipient": {"company_id": "12"},
    "letter": {
        "body": BODY,
        "recipient_attention": "Начальнику Каримову А. А.",
        "recipient_email": "gni@example.org",
    },
}
PDF_PENDING = {
    "status": "pending",
    "final": False,
    "error": None,
    "pages": None,
    "requested_at": NOW,
    "ready_at": None,
}
REGISTRAR = {"crm_user_id": 4, "full_name": "Регина Регистраторова"}


def letter(**over: Any) -> dict[str, Any]:
    return {
        "body": BODY,
        "recipient_attention": "Начальнику Каримову А. А.",
        "recipient_email": "gni@example.org",
        "signatory_name": None,
        "signatory_position": None,
        "pdf": None,
        "mailings": [],
        "registration_requested": None,
        **over,
    }


def letter_doc(**over: Any) -> dict[str, Any]:
    fields: dict[str, Any] = {
        "kind": "letter_out",
        "number": None,
        "recipient": {
            "name": "ГНИ Мирабадского района",
            "inn": None,
            "company_id": 12,
            "contact_id": None,
        },
        "letter": letter(),
        **over,
    }
    return document(**fields)


@pytest.fixture
def eds(be: Backends) -> EdsFake:
    # адресат письма — ссылкой на компанию ERP (СУЩ-2.6): BFF берёт название из её карточки
    be.router.get(f"{ERP_URL}/api/v1/parties/organizations/12/").mock(
        return_value=httpx.Response(
            200, json={"id": 12, "name": "ГНИ Мирабадского района", "inn": None, "people": []}
        )
    )
    return EdsFake(be)


async def test_create_letter_sends_body_and_registers_with_send(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["REGISTRAR"])
    eds.answer("POST", "documents", 201, letter_doc())
    sent = letter_doc(
        status="sent",
        number="ИСХ-012/26",
        letter=letter(
            pdf={**PDF_PENDING, "final": True},
            mailings=[
                {
                    "id": "50000000-0000-4000-8000-000000000001",
                    "to": ["gni@example.org"],
                    "status": "awaiting_pdf",
                    "reason": None,
                    "requested_by": REGISTRAR,
                    "requested_at": NOW,
                    "finished_at": None,
                }
            ],
        ),
    )
    eds.answer("POST", f"documents/{DOC_ID}/submit", 200, sent)

    response = await web.send(
        "POST", f"{BASE}/documents", json={**LETTER_FORM, "submit": True, "send": True}
    )

    assert response.status_code == 201, response.text
    check(response, "/eds/documents", "post")
    assert eds.body("POST", "documents")["letter"] == {
        "body": BODY,
        "recipient_attention": "Начальнику Каримову А. А.",
        "recipient_email": "gni@example.org",
    }
    assert eds.body("POST", f"documents/{DOC_ID}/submit") == {"send": True}
    card = response.json()
    assert card["letter"]["mailings"][0]["status"] == "awaiting_pdf"
    assert (card["can_register"], card["can_request_registration"]) == (False, False)


async def test_card_flags_for_executor_and_registrar(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    """Автор без права регистрации — «Передать на регистрацию»; регистрации без подписи нет
    (решение владельца 2026-11-21 (3)): переданный черновик тоже без «зарегистрировать»."""
    eds.answer("GET", f"documents/{DOC_ID}", 200, letter_doc())
    await web.login(["MANAGER"])
    mine = await web.client.get(f"{BASE}/documents/{DOC_ID}")
    assert mine.status_code == 200
    check(mine, "/eds/documents/{id}", "get")
    assert (mine.json()["can_register"], mine.json()["can_request_registration"]) == (False, True)

    handed = letter_doc(
        author={"crm_user_id": 5, "full_name": "Алия Каримова"},
        letter=letter(
            registration_requested={
                "by": {"crm_user_id": 5, "full_name": "Алия Каримова"},
                "at": EARLIER,
            }
        ),
    )
    eds.answer("GET", f"documents/{DOC_ID}", 200, handed)
    await web.login(["REGISTRAR"])
    seen = await web.client.get(f"{BASE}/documents/{DOC_ID}")
    check(seen, "/eds/documents/{id}", "get")
    assert (seen.json()["can_register"], seen.json()["can_request_registration"]) == (False, False)


async def test_author_registrar_can_hand_over_unless_he_can_sign_himself(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    """СЦ-9: делопроизводитель-автор без полномочия подписи передаёт письмо на подпись (раньше ни
    этого, ни «Подписать» у него не было); автор с полномочием (EDS `signing.can_sign`) подписывает
    сам, а «передать» ему не предлагается."""
    eds.answer("GET", f"documents/{DOC_ID}", 200, letter_doc())
    await web.login(["REGISTRAR"])
    seen = await web.client.get(f"{BASE}/documents/{DOC_ID}")
    check(seen, "/eds/documents/{id}", "get")
    flags = seen.json()
    assert (flags["can_sign"], flags["can_request_registration"]) == (False, True)

    signer = letter_doc(signing={"can_sign": True, "reason": None, "signer": None})
    eds.answer("GET", f"documents/{DOC_ID}", 200, signer)
    web.clock.advance(10)
    seen = await web.client.get(f"{BASE}/documents/{DOC_ID}")
    check(seen, "/eds/documents/{id}", "get")
    flags = seen.json()
    assert (flags["can_sign"], flags["can_request_registration"]) == (True, False)


async def test_pdf_request_status_and_stream(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    eds.answer("POST", f"documents/{DOC_ID}/pdf", 202, PDF_PENDING)
    eds.answer(
        "GET",
        f"documents/{DOC_ID}/pdf",
        200,
        {**PDF_PENDING, "status": "ready", "pages": 1, "ready_at": NOW},
    )
    eds.overrides[("GET", f"/api/v1/documents/{DOC_ID}/pdf/file")] = httpx.Response(
        200,
        content=b"%PDF-1.7 letter",
        headers={
            "content-type": "application/pdf",
            "content-disposition": "inline; filename*=UTF-8''letter.pdf",
        },
    )

    queued = await web.send("POST", f"{BASE}/documents/{DOC_ID}/pdf")
    assert queued.status_code == 202, queued.text
    check(queued, "/eds/documents/{id}/pdf", "post")
    ready = await web.client.get(f"{BASE}/documents/{DOC_ID}/pdf")
    check(ready, "/eds/documents/{id}/pdf", "get")
    assert ready.json()["pages"] == 1
    pdf = await web.client.get(f"{BASE}/documents/{DOC_ID}/pdf/file")
    assert pdf.status_code == 200
    assert pdf.content == b"%PDF-1.7 letter"
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("inline")
    assert pdf.headers["x-content-type-options"] == "nosniff"


async def test_pdf_errors_pass_through(web: Web, eds: EdsFake) -> None:
    await web.login(["MANAGER"])
    eds.error(
        "POST",
        f"documents/{DOC_ID}/pdf",
        409,
        "CONFLICT",
        "Бланк компании не задан — администратор сохраняет Настройки · Компания и бланки.",
        {"reason": "letterhead_missing"},
    )
    eds.error(
        "GET",
        f"documents/{DOC_ID}/pdf/file",
        409,
        "CONFLICT",
        "PDF ещё готовится.",
        {"reason": "pdf_not_ready"},
    )

    missing = await web.send("POST", f"{BASE}/documents/{DOC_ID}/pdf")
    assert missing.status_code == 409
    assert missing.json()["details"]["reason"] == "letterhead_missing"
    early = await web.client.get(f"{BASE}/documents/{DOC_ID}/pdf/file")
    assert early.status_code == 409
    assert early.json()["details"]["reason"] == "pdf_not_ready"


async def test_registration_request_and_send_again(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    eds.answer(
        "POST",
        f"documents/{DOC_ID}/registration-request",
        200,
        letter_doc(letter=letter(registration_requested={"by": ME, "at": NOW})),
    )
    await web.login(["MANAGER"])
    handed = await web.send("POST", f"{BASE}/documents/{DOC_ID}/registration-request")
    assert handed.status_code == 200, handed.text
    check(handed, "/eds/documents/{id}/registration-request", "post")
    assert handed.json()["letter"]["registration_requested"]["by"] == ME

    # «Отправить ещё раз» — только раздел регистрации исходящих: менеджеру 403 до EDS
    denied = await web.send("POST", f"{BASE}/documents/{DOC_ID}/send")
    assert denied.status_code == 403
    assert eds.requests("POST", f"documents/{DOC_ID}/send") == []

    eds.answer(
        "POST", f"documents/{DOC_ID}/send", 200, letter_doc(status="sent", number="ИСХ-012/26")
    )
    await web.login(["REGISTRAR"])
    again = await web.send("POST", f"{BASE}/documents/{DOC_ID}/send")
    assert again.status_code == 200, again.text
    check(again, "/eds/documents/{id}/send", "post")


async def test_undelivered_letter_is_flagged_and_can_be_waived(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    """СЦ-1: письмо не ушло — карточка говорит это полем; «вручено иначе» снимает отправку."""
    stuck = letter_doc(status="sent", number="ИСХ-012/26", letter=letter(undelivered=True))
    eds.answer("GET", f"documents/{DOC_ID}", 200, stuck)
    await web.login(["REGISTRAR"])
    card = await web.client.get(f"{BASE}/documents/{DOC_ID}")
    assert card.status_code == 200, card.text
    check(card, "/eds/documents/{id}", "get")
    assert card.json()["letter"]["undelivered"] is True

    waived = letter_doc(
        status="sent", number="ИСХ-012/26", letter=letter(undelivered=False, mail_waived_at=NOW)
    )
    eds.answer("POST", f"documents/{DOC_ID}/mail-waive", 200, waived)
    done = await web.send("POST", f"{BASE}/documents/{DOC_ID}/mail-waive")
    assert done.status_code == 200, done.text
    check(done, "/eds/documents/{id}/mail-waive", "post")
    assert done.json()["letter"]["undelivered"] is False
    assert done.json()["letter"]["mail_waived_at"]

    # снять отправку — раздел регистрации исходящих: менеджеру 403 до EDS
    await web.login(["MANAGER"])
    before = len(eds.requests("POST", f"documents/{DOC_ID}/mail-waive"))
    assert (await web.send("POST", f"{BASE}/documents/{DOC_ID}/mail-waive")).status_code == 403
    assert len(eds.requests("POST", f"documents/{DOC_ID}/mail-waive")) == before


async def test_letterhead_and_body_validation(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    eds.answer(
        "GET",
        "letterhead",
        200,
        {
            "configured": True,
            "company_name": "ООО «RailTech»",
            "requisites": ["г. Ташкент", "ИНН 305123456"],
            "signatory_name": "Каримов А. А.",
            "signatory_position": "Директор",
            "has_logo": True,
            "updated_at": NOW,
        },
    )
    head = await web.client.get(f"{BASE}/letterhead")
    assert head.status_code == 200
    check(head, "/eds/letterhead", "get")

    bad_email = {**LETTER_FORM, "letter": {**LETTER_FORM["letter"], "recipient_email": "не почта"}}
    bad_body = {
        **LETTER_FORM,
        "letter": {**LETTER_FORM["letter"], "body": {"version": 2, "lang": "ru", "doc": {}}},
    }
    for form in (bad_email, bad_body):
        assert (await web.send("POST", f"{BASE}/documents", json=form)).status_code == 422
    assert eds.requests("POST", "documents") == []


async def test_chosen_signer_goes_to_eds_and_comes_back_on_the_card(
    web: Web, eds: EdsFake, check: ContractChecker
) -> None:
    """ЕД-6: выбранный подписант и «и. о.» уходят в EDS как есть; имя из справочника берёт EDS."""
    await web.login(["REGISTRAR"])
    eds.answer(
        "POST",
        "documents",
        201,
        letter_doc(
            letter=letter(
                signatory_name="Рустам Директоров",
                signatory_position="И. о. директора",
                signer_crm_user_id=3,
            )
        ),
    )
    form = {
        **LETTER_FORM,
        "letter": {
            **LETTER_FORM["letter"],
            "signer_crm_user_id": 3,
            "signatory_position": "И. о. директора",
        },
    }

    response = await web.send("POST", f"{BASE}/documents", json=form)

    assert response.status_code == 201, response.text
    check(response, "/eds/documents", "post")
    sent = eds.body("POST", "documents")["letter"]
    assert (sent["signer_crm_user_id"], sent["signatory_position"]) == (3, "И. о. директора")
    assert response.json()["letter"]["signer_crm_user_id"] == 3

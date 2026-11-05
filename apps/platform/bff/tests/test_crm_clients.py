"""Клиенты · Клиенты (W16-D1-2b, контракт BFF, тег `clients`): прокси к CRM.

CRM — на respx (`crm_leads_support`), ответы BFF сверяются со схемами platform-bff.yaml. Проверяется
то, что делает BFF: раздел `crm.clients` (чтение — список и карточка, полный — повтор приглашения;
403 — до CRM), порядок «сначала недавно активные», карточка 360° (каналы контакта, лиды, заявки с
шагом пути и «что видит клиент», документы), карточка по частям при сбое CRM (`sources`), что не
уходит в браузер (заметки клиента, примечание контакта), 404 клиента.
"""

import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.crm_leads_support import LETTER_ID, CrmLeadsFake, client_detail, deal, invitation_out

BASE = "/api/v1/crm/clients"


@pytest.fixture
def crm(be: Backends) -> CrmLeadsFake:
    return CrmLeadsFake(be)


async def test_without_the_clients_section_everything_is_forbidden_before_crm(
    web: Web, crm: CrmLeadsFake
) -> None:
    await web.login(["ADMIN"])
    assert (await web.client.get(BASE)).status_code == 403
    assert (await web.client.get(f"{BASE}/12")).status_code == 403
    assert crm.calls == []


async def test_reader_cannot_resend_the_invitation(web: Web, crm: CrmLeadsFake) -> None:
    await web.login(["SUPPLY"])  # клиенты — только чтение
    response = await web.send("POST", f"{BASE}/12/invitation", json={"channel": "telegram"})
    assert response.status_code == 403
    assert crm.calls == []


async def test_list_puts_recently_active_first(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    response = check(await web.client.get(f"{BASE}?q=%20Демо%20"), "/crm/clients", "get")

    items = response.json()["items"]
    assert [i["id"] for i in items] == [14, 12, 13]
    assert items[1] == {
        "id": 12,
        "name": "ООО Демо-Логистик",
        "inn": "000000001",
        "in_erp": True,
        "open_requests": 2,
        "last_activity_at": "2026-10-27T08:48:00Z",
        "handoff_status": "done",
    }
    assert items[2]["in_erp"] is False
    assert crm.params("GET", "clients") == {"q": "Демо"}
    assert "внутренняя заметка" not in response.text


async def test_card_360_collects_contacts_leads_requests_and_documents(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    response = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get")

    card = response.json()
    assert (card["name"], card["segment"], card["in_erp"]) == (
        "ООО Демо-Логистик",
        "logistics",
        True,
    )
    assert card["handoff"] == {"status": "done", "error": None}
    assert card["sources"] == {"contacts": "ok", "requests": "ok", "documents": "ok"}
    first, second = card["contacts"]
    assert first == {
        "id": 51,
        "name": "Азиз Демо",
        "position": "Снабжение",
        "phone": "+998900000000",
        "email": None,
        "telegram": "aziz_demo",
        "channels": ["telegram", "phone"],
        "preferred_channel": "telegram",
        "is_primary": True,
    }
    assert second["channels"] == ["email"]
    assert second["telegram"] is None
    assert card["leads"] == [
        {
            "lead": "L-2041",
            "name": "Азиз Демо",
            "status": "client",
            "last_message_at": "2026-10-27T09:00:00Z",
        }
    ]
    quote, failed, paid, lost = card["requests"]
    assert quote == {
        "deal": 77,
        "number": "ЗВ-2026-104",
        "title": "Рельсы Р65",
        "summary": "Рельсы Р65, 40 т",
        "step": "QUOTE",
        "project": False,
        "client_sees": "awaiting_decision",
        "urgency": "urgent",
        "transfer": "done",
        "transfer_error": None,
        "created_at": "2026-10-27T08:48:00Z",
        "letter_file_id": LETTER_ID,
    }
    assert (failed["number"], failed["step"], failed["client_sees"]) == (None, "REQUEST", "in_work")
    assert (failed["transfer"], failed["transfer_error"]) == ("failed", "erp_unreachable")
    assert (paid["step"], paid["project"], paid["client_sees"]) == ("PAYMENT", True, "fulfilling")
    assert (lost["step"], lost["client_sees"]) == ("LOST", "rejected")
    assert card["documents"] == [
        {
            "id": 61,
            "title": "Договор поставки",
            "type": "contract",
            "number": "Д-17",
            "date": "2026-10-20",
            "visible_to_client": True,
        },
        {
            "id": 62,
            "title": "Договор поставки",
            "type": "other",
            "number": "Д-17",
            "date": None,
            "visible_to_client": True,
        },
    ]
    assert card["invitation"]["status"] == "sent"
    assert crm.params("GET", "deals") == {"client_id": "12"}
    assert crm.params("GET", "documents") == {"client_id": "12"}
    for leak in ("внутренняя заметка", "звонить после обеда", "dogovor.pdf"):
        assert leak not in response.text


async def test_card_does_not_leak_deal_amount_or_owner(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    """Сумма сделки CRM и её владелец в карточку клиента не попадают (деньги — разделы ERP/EDS)."""
    crm.answer(
        "GET",
        "deals",
        body=[deal(77, amount="125000000.00", currency="UZS", owner_name="Дилшод Менеджеров")],
    )
    await web.login(["MANAGER"])
    response = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get")

    (row,) = response.json()["requests"]
    assert not {"amount", "currency", "owner_user_id", "owner_name"} & row.keys()
    assert "125000000" not in response.text


async def test_card_shows_what_crm_gave_when_parts_fail(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer("GET", "documents", 503, {"code": "unavailable"})
    crm.answer("GET", "clients/12/contacts", 403, {"code": "forbidden"})
    await web.login(["MANAGER"])
    card = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get").json()

    assert card["sources"] == {
        "contacts": "unavailable",
        "requests": "ok",
        "documents": "unavailable",
    }
    assert (card["contacts"], card["documents"]) == ([], [])
    assert len(card["requests"]) == 4


async def test_unknown_client_is_404(web: Web, crm: CrmLeadsFake, check: ContractChecker) -> None:
    await web.login(["MANAGER"])
    response = check(await web.client.get(f"{BASE}/99"), "/crm/clients/{id}", "get")
    assert response.json()["code"] == "NOT_FOUND"


PARTNER_REQUEST = {
    "id": 31,
    "erp_company_id": 214,
    "company_name": "Демо Мануфактуринг ООО",
    "matched_by": "inn",
    "contacts": [{"full_name": "Иванов Пётр", "email": "ivanov@manufacturing.example"}],
    "created_at": "2026-11-04T09:15:00Z",
}


async def test_card_shows_partners_waiting_for_the_managers_decision(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    """PART-CRM: партнёр ERP, похожий на клиента, ждёт подтверждения: карточка отдаёт его заявку."""
    crm.answer("GET", "clients/12", body=client_detail(12, partner_requests=[PARTNER_REQUEST]))
    await web.login(["SUPPLY"])

    response = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get")

    assert response.json()["partner_requests"] == [PARTNER_REQUEST]


async def test_card_without_waiting_partners_has_an_empty_list(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])
    response = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get")
    assert response.json()["partner_requests"] == []


async def test_manager_confirms_a_partner_request(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer("POST", "clients/12/partner-requests/31/confirm", body={"ok": True})
    await web.login(["MANAGER"])

    response = check(
        await web.send("POST", f"{BASE}/12/partner-requests/31/confirm"),
        "/crm/clients/{id}/partner-requests/{request_id}/confirm",
        "post",
    )

    assert response.json() == {"client_id": 12}


async def test_manager_declines_a_partner_request_and_gets_the_new_client(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer("POST", "clients/12/partner-requests/31/decline", 201, {"id": 77})
    await web.login(["MANAGER"])

    response = check(
        await web.send("POST", f"{BASE}/12/partner-requests/31/decline"),
        "/crm/clients/{id}/partner-requests/{request_id}/decline",
        "post",
    )

    assert response.json() == {"client_id": 77}


async def test_partner_request_decision_needs_the_full_clients_right_and_keeps_crm_refusals(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["SUPPLY"])  # клиенты — только чтение
    for action in ("confirm", "decline"):
        denied = await web.send("POST", f"{BASE}/12/partner-requests/31/{action}")
        assert denied.status_code == 403
    assert crm.calls == []

    await web.login(["MANAGER"])
    crm.error("POST", "clients/12/partner-requests/31/confirm", 404, "not_found")
    gone = check(
        await web.send("POST", f"{BASE}/12/partner-requests/31/confirm"),
        "/crm/clients/{id}/partner-requests/{request_id}/confirm",
        "post",
    )
    assert gone.status_code == 404
    crm.error("POST", "clients/12/partner-requests/32/confirm", 409, "conflict")
    taken = check(
        await web.send("POST", f"{BASE}/12/partner-requests/32/confirm"),
        "/crm/clients/{id}/partner-requests/{request_id}/confirm",
        "post",
    )
    assert taken.status_code == 409


async def test_resend_invitation_returns_the_result_of_crm(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["MANAGER"])
    body = {"channel": "telegram", "contact_id": 51}
    response = check(
        await web.send("POST", f"{BASE}/12/invitation", json=body),
        "/crm/clients/{id}/invitation",
        "post",
    )
    assert response.json() == {
        "status": "sent",
        "channel": "telegram",
        "sent_via": ["telegram"],
        "sent_at": "2026-10-27T09:00:00Z",
        "contact_name": "Азиз Демо",
        "error_text": "У контакта нет почты",
        "available_channels": ["telegram"],
        "suggested_channel": "telegram",
        "can_resend": True,
    }
    assert crm.body("POST", "clients/12/invitation") == body


async def test_resend_invitation_refusal_keeps_the_reason(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.error("POST", "clients/12/invitation", 409, "conflict", reason="client_not_in_erp")
    await web.login(["MANAGER"])
    response = check(
        await web.send("POST", f"{BASE}/12/invitation", json={"channel": "email"}),
        "/crm/clients/{id}/invitation",
        "post",
    )
    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"
    assert response.json()["details"]["reason"] == "client_not_in_erp"


async def test_resend_by_email_is_queued_until_the_mail_service_sends_it(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    """B-MAIL-1: CRM отвечает «в очереди», пока почта не отправила письмо.

    BFF не выдаёт это за «отправлено»."""
    crm.answer(
        "POST",
        "clients/12/invitation",
        body=invitation_out(status="queued", error=None, error_text=None, sent_via=["email"]),
    )
    await web.login(["MANAGER"])
    response = check(
        await web.send("POST", f"{BASE}/12/invitation", json={"channel": "email"}),
        "/crm/clients/{id}/invitation",
        "post",
    )
    assert (response.json()["status"], response.json()["sent_at"]) == ("queued", None)


async def test_card_shows_mail_not_configured_in_words(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    """B-MAIL-1: письмо приглашения не ушло — причина словами CRM доходит до карточки как есть."""
    reason = "Почта не настроена (Настройки · Подключения · Почта), письмо не отправлено."
    crm.answer(
        "GET",
        "clients/12",
        body={
            **client_detail(12),
            "invitation": invitation_out(error="smtp_not_configured", error_text=reason),
        },
    )
    await web.login(["MANAGER"])
    response = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get")
    invitation = response.json()["invitation"]
    assert (invitation["status"], invitation["error_text"]) == ("failed", reason)
    assert invitation["can_resend"] is True

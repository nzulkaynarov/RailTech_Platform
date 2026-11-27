"""Клиенты · Клиенты (W16-D1-2b, контракт BFF, тег `clients`): прокси к CRM.

CRM — на respx (`crm_leads_support`), ответы BFF сверяются со схемами platform-bff.yaml. Проверяется
то, что делает BFF: раздел `crm.clients` (чтение — список и карточка, полный — повтор приглашения;
403 — до CRM), порядок «сначала недавно активные», карточка 360° (каналы контакта, лиды, заявки с
шагом пути и «что видит клиент», документы), карточка по частям при сбое CRM (`sources`), что не
уходит в браузер (заметки клиента, примечание контакта), 404 клиента.
"""

from datetime import UTC, datetime

import httpx
import pytest

from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.crm_leads_support import (
    LETTER_ID,
    CrmLeadsFake,
    client_detail,
    client_item,
    contact,
    deal,
    invitation_out,
)
from tests.eds_projects_support import ProjectsFake
from tests.eds_projects_support import row as project_row

BASE = "/api/v1/crm/clients"


LOGOS = f"{ERP_URL}/api/v1/parties/organizations/logos/"
ROLES = f"{ERP_URL}/api/v1/parties/organizations/role-states/"


@pytest.fixture(autouse=True)
def erp_logos(be: Backends) -> None:
    """ERP отдаёт версию логотипа только компании 501 (ЕД-5): остальные строки — без логотипа."""
    be.router.get(LOGOS).mock(
        return_value=httpx.Response(200, json={"results": {"501": "a1b2c3d4e5"}})
    )
    # КОНТР-1б: роли строк списка — ERP; у компании 501 она клиент, у остальных ответа нет
    be.router.get(ROLES).mock(
        return_value=httpx.Response(
            200, json={"results": {"501": [{"role": "client", "state": "active", "kind": None}]}}
        )
    )


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


@pytest.fixture(autouse=True)
def erp_projects(be: Backends) -> ProjectsFake:
    """ERP отвечает на «проекты клиента» (слово проекта в карточке); по умолчанию проектов нет."""
    fake = ProjectsFake(be)
    fake.rows = []
    fake.cards = {}
    return fake


async def test_reader_cannot_resend_the_invitation(web: Web, crm: CrmLeadsFake) -> None:
    await web.login(["SUPPLY"])  # клиенты — только чтение
    response = await web.send("POST", f"{BASE}/12/invitation", json={"channel": "telegram"})
    assert response.status_code == 403
    assert crm.calls == []


async def test_list_puts_recently_active_first(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])  # 0.3 (FR-13): у снабженца клиентов CRM больше нет
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
        "do_not_work": False,
        "is_test": False,
        "logo_url": "/api/v1/people/counterparties/501/logo?v=a1b2c3d4e5",
        "company_id": "501",
        "roles": [{"role": "client", "state": "active", "kind": None}],
    }
    assert items[2]["in_erp"] is False
    assert items[2]["logo_url"] is None
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
        "email_problem": None,
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
        "cabinet_status": "quoted",
        "urgency": "urgent",
        "transfer": "done",
        "transfer_error": None,
        "created_at": "2026-10-27T08:48:00Z",
        "letter_file_id": LETTER_ID,
    }
    assert (failed["number"], failed["step"], failed["client_sees"]) == (None, "REQUEST", "in_work")
    assert (failed["transfer"], failed["transfer_error"]) == ("failed", "erp_unreachable")
    assert failed["cabinet_status"] == "new"
    assert (paid["step"], paid["project"], paid["client_sees"]) == ("PAYMENT", True, "fulfilling")
    assert paid["cabinet_status"] is None  # проект: слова проекта, не заявки
    assert (lost["step"], lost["client_sees"], lost["cabinet_status"]) == (
        "LOST",
        "rejected",
        "closed",
    )
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
    await web.login(["ENGINEER"])  # 0.3 (FR-13): у снабженца клиентов CRM больше нет

    response = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get")

    assert response.json()["partner_requests"] == [PARTNER_REQUEST]


async def test_card_without_waiting_partners_has_an_empty_list(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["ENGINEER"])  # 0.3 (FR-13): у снабженца клиентов CRM больше нет
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


# --- Х-8: «Не работать» из ERP в карточке и списке клиента ---------------------------------------

MARK = {
    "reason": "Спор по оплате",
    "set_by": "Менеджер Демо",
    "set_at": "2026-11-23T09:30:00Z",
    "until": "2026-12-31",
}


async def test_card_and_list_show_the_do_not_work_mark_from_erp(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer("GET", "clients/12", body=client_detail(12, do_not_work=MARK))
    crm.answer("GET", "clients", body=[client_item(12, do_not_work=MARK), client_item(13)])
    await web.login(["DIRECTOR"])

    card = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get").json()
    assert card["do_not_work"] == MARK
    items = check(await web.client.get(BASE), "/crm/clients", "get").json()["items"]
    assert {row["id"]: row["do_not_work"] for row in items} == {12: True, 13: False}


async def test_test_companies_are_out_of_the_list_unless_asked(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    """ТЕСТ-1: без `test` CRM тестовых не отдаёт; `test=only` («Тестовые») уходит в CRM как есть."""
    crm.answer("GET", "clients", body=[client_item(21, is_test=True)])
    crm.answer("GET", "clients/21", body=client_detail(21, is_test=True))
    await web.login(["DIRECTOR"])

    items = check(await web.client.get(f"{BASE}?test=only"), "/crm/clients", "get").json()["items"]
    assert [(row["id"], row["is_test"]) for row in items] == [(21, True)]
    assert crm.params("GET", "clients") == {"test": "only"}
    card = check(await web.client.get(f"{BASE}/21"), "/crm/clients/{id}", "get").json()
    assert card["is_test"] is True

    await web.client.get(BASE)
    assert crm.params("GET", "clients") == {}
    assert (await web.client.get(f"{BASE}?test=junk")).status_code == 422


async def test_card_without_the_mark_has_none(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    await web.login(["DIRECTOR"])
    card = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get").json()
    assert card["do_not_work"] is None


async def test_list_still_works_without_logos_when_erp_refuses(
    web: Web, be: Backends, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    be.router.get(LOGOS).mock(return_value=httpx.Response(503, json={"detail": "down"}))
    await web.login(["DIRECTOR"])
    items = check(await web.client.get(BASE), "/crm/clients", "get").json()["items"]
    assert items
    assert all(row["logo_url"] is None for row in items)


async def test_list_asks_erp_for_the_companies_of_the_rows_only(
    web: Web, be: Backends, crm: CrmLeadsFake
) -> None:
    await web.login(["DIRECTOR"])
    await web.client.get(BASE)
    calls = [c for r in be.router.routes for c in r.calls if str(c.request.url).startswith(LOGOS)]
    assert calls
    assert dict(calls[-1].request.url.params) == {"ids": "501"}


async def test_list_fetches_logos_in_batches_for_every_row(
    web: Web, be: Backends, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    """CRM отдаёт до 500 строк: логотипы просят пачками по 100, свежие строки не теряются."""
    asked: list[list[int]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        ids = [int(i) for i in request.url.params["ids"].split(",")]
        asked.append(ids)
        return httpx.Response(200, json={"results": {str(i): f"v{i}" for i in ids}})

    be.router.get(LOGOS).mock(side_effect=answer)
    rows = [client_item(1000 + n, erp_company_id=2000 + n) for n in range(250)]
    crm.answer("GET", "clients", body=rows)
    await web.login(["DIRECTOR"])
    items = check(await web.client.get(BASE), "/crm/clients", "get").json()["items"]
    assert [len(batch) for batch in asked] == [100, 100, 50]
    assert all(row["logo_url"] for row in items)
    newest = next(row for row in items if row["id"] == 1249)
    assert newest["logo_url"] == "/api/v1/people/counterparties/2249/logo?v=v2249"


async def test_card_360_marks_a_contact_whose_letters_do_not_arrive(
    web: Web, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    crm.answer(
        "GET",
        "clients/12/contacts",
        body={
            "contacts": [
                contact(
                    52,
                    email="gone@old.example",
                    telegram_identity_id=None,
                    email_undeliverable={
                        "kind": "permanent",
                        "reason": "mailbox_not_found",
                        "last_at": "2026-11-24T10:15:00Z",
                        "reports": 1,
                    },
                )
            ],
            "suggestions": [],
        },
    )
    await web.login(["DIRECTOR"])
    card = check(await web.client.get(f"{BASE}/12"), "/crm/clients/{id}", "get").json()
    assert card["contacts"][0]["email_problem"] == {
        "reason": "mailbox_not_found",
        "at": "2026-11-24T10:15:00Z",
    }


@pytest.mark.parametrize(
    ("external_stage", "expected"),
    [
        (
            "accepted",
            "contract_preparing",
        ),  # КП принято, договора у клиента нет: согласовывать нечего (СЦ-8)
        ("contract", "contract_review"),
        ("invoiced", "awaiting_payment"),
    ],
)
def test_client_sees_follows_the_erp_stage_not_only_the_step(
    external_stage: str, expected: str
) -> None:
    from types import SimpleNamespace

    from app.crm_clients_view import request_row

    deal = SimpleNamespace(
        id=1,
        erp_number="ЗВ-1",
        title="Т",
        request_summary="",
        stage="open",
        external_stage=external_stage,
        request_urgency="normal",
        erp_request_status="done",
        erp_request_error=None,
        created_at=datetime(2026, 11, 1, tzinfo=UTC),
        request_letter_file_id=None,
    )
    assert request_row(deal).client_sees == expected  # type: ignore[arg-type]


async def test_list_takes_the_relation_type_from_erp_roles(
    web: Web, be: Backends, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    """КОНТР-1б: в списке «Клиент» и «Партнёр» говорит ERP, а не то, что строка пришла из CRM."""
    await web.login(["DIRECTOR"])
    items = check(await web.client.get(BASE), "/crm/clients", "get").json()["items"]
    row = next(r for r in items if r["company_id"] == "501")
    assert row["roles"] == [{"role": "client", "state": "active", "kind": None}]
    assert all(r["roles"] is None for r in items if r["company_id"] is None)


async def test_list_survives_when_erp_cannot_name_the_roles(
    web: Web, be: Backends, crm: CrmLeadsFake, check: ContractChecker
) -> None:
    be.router.get(ROLES).mock(return_value=httpx.Response(503, json={"detail": "down"}))
    await web.login(["DIRECTOR"])
    items = check(await web.client.get(BASE), "/crm/clients", "get").json()["items"]
    assert items
    assert all(row["roles"] is None for row in items)


async def test_card_takes_the_project_word_from_erp_after_the_client_agrees(
    web: Web, erp_projects: ProjectsFake, crm: CrmLeadsFake
) -> None:
    """ПРАВДА-2: после «Принять редакцию» в Кабинете карточка не пишет «Согласуйте редакцию»."""
    erp = erp_projects
    erp.rows = [project_row(7, client_status="contract_signing")]  # ПР-2026-007 — проект сделки 79
    await web.login(["DIRECTOR"])

    card = (await web.client.get(f"{BASE}/12")).json()

    project = next(r for r in card["requests"] if r["number"] == "ПР-2026-007")
    assert (project["project"], project["client_sees"]) == (True, "contract_signing")
    quote = next(r for r in card["requests"] if r["number"] == "ЗВ-2026-104")
    assert quote["client_sees"] == "awaiting_decision"  # заявки ERP не спрашиваем


async def test_card_keeps_the_mirror_word_when_erp_does_not_answer(
    web: Web, erp_projects: ProjectsFake, crm: CrmLeadsFake
) -> None:
    erp_projects.answer("GET", r"projects/", httpx.Response(502, json={"detail": "x"}))
    await web.login(["DIRECTOR"])

    card = (await web.client.get(f"{BASE}/12")).json()

    project = next(r for r in card["requests"] if r["number"] == "ПР-2026-007")
    assert project["client_sees"] == "fulfilling"

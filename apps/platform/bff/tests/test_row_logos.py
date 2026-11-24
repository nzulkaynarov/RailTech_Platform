"""Логотип компании в строках проектов, счетов и писем (ЕД-3, ЕД-5).

ERP и EDS — на respx. Проверяется то, что делает BFF: версии логотипов берутся у ERP одним
пакетным запросом на список (повторы схлопнуты, не по запросу на строку), каждая строка с компанией
получает наш путь `…/logo?v=`, адресов хранилища в ответе нет, а отказ ERP не ломает реестр.
"""

import httpx
import pytest

from app.cookies import CSRF_HEADER
from tests.backends import Backends
from tests.conftest import ContractChecker, Web
from tests.consts import ERP_URL
from tests.eds_letters_support import EdsFake
from tests.eds_letters_support import row as letter_row
from tests.eds_payments_support import TODAY, PaymentsFake, invoice
from tests.eds_projects_support import ProjectsFake, card
from tests.eds_projects_support import row as project_row
from tests.roles import custom

LOGOS = f"{ERP_URL}/api/v1/parties/organizations/logos/"
LOGO_7 = "/api/v1/people/counterparties/7/logo?v=v7"
LOGO_9 = "/api/v1/people/counterparties/9/logo?v=v9"
STORAGE_MARKS = ("http://", "https://", "s3", "minio", "amazonaws", "/media/")


@pytest.fixture
def asked(be: Backends) -> list[list[int]]:
    """ERP отдаёт версии `v<id>` компаниям 7 и 9; список вызовов — по id в каждом запросе."""
    calls: list[list[int]] = []

    def answer(request: httpx.Request) -> httpx.Response:
        ids = [int(i) for i in request.url.params["ids"].split(",")]
        calls.append(ids)
        return httpx.Response(200, json={"results": {str(i): f"v{i}" for i in ids if i in (7, 9)}})

    be.router.get(LOGOS).mock(side_effect=answer)
    return calls


def no_storage_address(items: list[dict[str, object]], key: str) -> None:
    for item in items:
        value = item.get(key)
        assert value is None or not any(m in str(value) for m in STORAGE_MARKS), value


async def test_projects_list_asks_erp_once_and_carries_the_logo_in_every_row(
    web: Web, be: Backends, asked: list[list[int]], check: ContractChecker
) -> None:
    erp = ProjectsFake(be)
    erp.rows = [
        project_row(104),
        project_row(105),
        project_row(106, company_id=9),
        project_row(107, company_id=None),
    ]
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/eds/projects")

    items = check(response, "/eds/projects", "get").json()["items"]
    assert [i["client_logo_url"] for i in items] == [LOGO_7, LOGO_7, LOGO_9, None]
    assert [i["client_id"] for i in items] == [7, 7, 9, None]
    assert asked == [[7, 9]], "один пакетный запрос на весь список, повторы схлопнуты"
    no_storage_address(items, "client_logo_url")


async def test_project_card_carries_the_logo(
    web: Web, be: Backends, asked: list[list[int]], check: ContractChecker
) -> None:
    ProjectsFake(be)
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/eds/projects/ПР-2026-104")

    body = check(response, "/eds/projects/{ref}", "get").json()
    assert body["client_logo_url"] == LOGO_7


async def test_payments_board_asks_erp_once_and_carries_the_logo(
    web: Web, be: Backends, asked: list[list[int]], check: ContractChecker
) -> None:
    fake = PaymentsFake(be)
    fake.invoices = {
        142: invoice(142),
        143: invoice(143, client_id=9),
        144: invoice(144, client_id=7),
    }
    await web.login(["ACCOUNTANT"])

    response = await web.client.get("/api/v1/eds/payments", params={"tab": "all"})

    items = check(response, "/eds/payments", "get").json()["items"]
    assert {i["id"]: i["client_logo_url"] for i in items} == {142: LOGO_7, 143: LOGO_9, 144: LOGO_7}
    assert asked == [[7, 9]]
    no_storage_address(items, "client_logo_url")


async def test_letters_list_asks_erp_once_and_carries_the_logo(
    web: Web, be: Backends, asked: list[list[int]], check: ContractChecker
) -> None:
    eds = EdsFake(be)
    other = letter_row(id="2" * 8 + "-0000-4000-8000-000000000104")
    other["links"] = {**other["links"], "erp_company_id": 9}
    unlinked = letter_row(id="3" * 8 + "-0000-4000-8000-000000000104")
    unlinked["links"] = {**unlinked["links"], "erp_company_id": None}
    eds.page = {"items": [letter_row(), other, unlinked], "next_cursor": None}
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/eds/letters")

    items = check(response, "/eds/letters", "get").json()["items"]
    # письмо без компании поле не несёт совсем (ответ списка писем без неустановленных полей)
    assert [i.get("client_logo_url") for i in items] == [LOGO_7, LOGO_9, None]
    assert asked == [[7, 9]]
    no_storage_address(items, "client_logo_url")


async def test_list_still_works_without_logos_when_erp_refuses(
    web: Web, be: Backends, check: ContractChecker
) -> None:
    ProjectsFake(be)
    be.router.get(LOGOS).mock(return_value=httpx.Response(503, json={"detail": "down"}))
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/eds/projects")

    items = check(response, "/eds/projects", "get").json()["items"]
    assert items
    assert all(i["client_logo_url"] is None and i["client_id"] == 7 for i in items)


async def test_rows_without_a_company_do_not_call_erp_at_all(
    web: Web, be: Backends, asked: list[list[int]]
) -> None:
    erp = ProjectsFake(be)
    erp.rows = [project_row(104, company_id=None)]
    await web.login(["DIRECTOR"])

    assert (await web.client.get("/api/v1/eds/projects")).status_code == 200
    assert asked == []


PROJECTS_ONLY = custom(70, "Только проекты", {"eds.projects": "read"})
NO_COMPANY_SECTION = custom(71, "Без разделов с контрагентами", {"dashboard.queue": "full"})


async def test_a_reader_of_projects_gets_logos_and_may_fetch_the_picture(
    web: Web, be: Backends, asked: list[list[int]]
) -> None:
    """Раздел, в котором строка показывает клиента, открывает и картинку его логотипа (ЕД-3)."""
    ProjectsFake(be)
    be.router.get(f"{ERP_URL}/api/v1/parties/organizations/7/logo/").mock(
        return_value=httpx.Response(200, content=b"RIFF", headers={"content-type": "image/webp"})
    )
    await web.login([PROJECTS_ONLY])

    items = (await web.client.get("/api/v1/eds/projects")).json()["items"]
    picture = await web.client.get(items[0]["client_logo_url"])

    assert items[0]["client_logo_url"] == LOGO_7
    assert picture.status_code == 200
    assert picture.headers["content-type"] == "image/webp"


async def test_a_role_without_any_company_section_cannot_fetch_the_picture(
    web: Web, be: Backends
) -> None:
    await web.login([NO_COMPANY_SECTION])
    assert (await web.client.get("/api/v1/people/counterparties/7/logo")).status_code == 403


async def test_project_card_after_an_action_keeps_the_logo(
    web: Web, be: Backends, asked: list[list[int]], check: ContractChecker
) -> None:
    """Ответ действия SPA кладёт в кэш карточки: логотип не должен превращаться в буквы."""
    erp = ProjectsFake(be)
    erp.cards[104] = card(contract=None, can_create_contract=True)
    await web.login(["ACCOUNTANT"])

    response = await web.send("POST", "/api/v1/eds/projects/ПР-2026-104/contract/draft")

    assert response.status_code == 201
    assert (
        check(response, "/eds/projects/{ref}/contract/draft", "post").json()["client_logo_url"]
        == LOGO_7
    )


async def test_payment_card_after_an_action_keeps_the_logo(
    web: Web, be: Backends, asked: list[list[int]], check: ContractChecker
) -> None:
    PaymentsFake(be)
    await web.login(["ACCOUNTANT"])

    response = await web.client.post(
        "/api/v1/eds/payments/142/confirm",
        json={"amount": "112000000.00", "date": TODAY, "reference": "B-1"},
        headers={CSRF_HEADER: web.csrf, "Idempotency-Key": "attempt-0002"},
    )

    assert response.status_code == 200, response.json()
    assert check(response, "/eds/payments/{id}/confirm", "post").json()["client_logo_url"] == LOGO_7


@pytest.mark.parametrize("section", ["eds.inbox", "eds.payments"])
async def test_a_narrow_role_asking_for_an_arbitrary_company_gets_erp_404_with_its_own_token(
    web: Web, be: Backends, section: str
) -> None:
    """Раздел EDS открывает ручку, не контрагентов: чужую компанию отсекает ERP по токену."""
    route = be.router.get(f"{ERP_URL}/api/v1/parties/organizations/9999/logo/").mock(
        return_value=httpx.Response(404, json={"detail": "Not found."})
    )
    await web.login([custom(72, "Узкая роль", {section: "read"})])

    response = await web.client.get("/api/v1/people/counterparties/9999/logo")

    assert response.status_code == 404
    [call] = route.calls
    assert call.request.headers["authorization"].startswith("Bearer ey")  # токен ERP сотрудника


async def test_people_list_carries_company_logos_in_one_batch(
    web: Web, be: Backends, asked: list[list[int]], check: ContractChecker
) -> None:
    """ЕД-3: «Люди» — логотип компании контакта пакетом на весь список, как в реестрах."""
    person = {
        "has_email": False,
        "has_phone": False,
        "is_primary": False,
        "position": "",
        "kind": "client",
    }
    page = {
        "count": 3,
        "next": None,
        "previous": None,
        "results": [
            {"id": 1, "name": "А", "company": {"id": 7, "name": "ООО Юг"}, **person},
            {"id": 2, "name": "Б", "company": {"id": 7, "name": "ООО Юг"}, **person},
            {"id": 3, "name": "В", "company": {"id": 9, "name": "ООО Север"}, **person},
        ],
    }
    be.router.get(f"{ERP_URL}/api/v1/parties/people/").mock(
        return_value=httpx.Response(200, json=page)
    )
    await web.login(["DIRECTOR"])

    response = await web.client.get("/api/v1/people/contacts")

    items = check(response, "/people/contacts", "get").json()["items"]
    assert [i["company_logo_url"] for i in items] == [LOGO_7, LOGO_7, LOGO_9]
    assert asked == [[7, 9]], "один пакетный запрос на весь список"
    no_storage_address(items, "company_logo_url")

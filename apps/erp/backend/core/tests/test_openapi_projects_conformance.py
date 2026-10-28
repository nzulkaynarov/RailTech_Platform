"""D2-5: проекты, статусы договора и скан акта отвечают так, как обещает выгрузка `erp-internal.yaml` (сторож по образцу D2-0).

Каждая новая операция вызывается живым кодом, и тело ответа сверяется со схемой из контракта — в том числе отказы
(`403`, `404`, `409`, `400`): форма ответа и коды описаны, а не угаданы. Поведение API файл не меняет.
"""

import pytest
from integration.tests import world as w

from core.tests.openapi_fixtures import API, conforms
from core.tests.openapi_internal import response_errors  # noqa: F401
from crm.constants import ActStatusCode as A
from crm.constants import ContractStatusCode as S
from crm.constants import InvoiceStatusCode
from crm.tests.projects_world import PDF, api, contract_in, pw, scan  # noqa: F401

pytestmark = pytest.mark.django_db

PROJECTS = f"{API}crm/projects/"
CONTRACTS = f"{API}crm/contracts/"
ACTS = f"{API}crm/acts/"


def test_projects_list_and_card_follow_the_contract(pw):  # noqa: F811
    contract_in(pw, S.PENDING_CLIENT)
    client = api(pw.director)
    conforms(client.get(PROJECTS), PROJECTS, "get", status=200)
    conforms(client.get(f"{PROJECTS}{pw.deal.id}/"), f"{PROJECTS}{{deal_id}}/", "get", status=200)
    conforms(client.get(f"{PROJECTS}999999/"), f"{PROJECTS}{{deal_id}}/", "get", status=404)
    conforms(api(pw.stranger).get(PROJECTS), PROJECTS, "get", status=403)


def test_card_with_every_document_follows_the_contract(pw):  # noqa: F811
    contract = contract_in(pw, S.SIGNED)
    invoice = w.add_invoice(pw.deal, InvoiceStatusCode.PAID, total="5", paid="5", contract=contract)
    w.add_act(pw.deal, A.SIGNED, contract=contract, invoice=invoice)
    w.add_fulfillment(pw.deal, "SHIPPED")
    conforms(api(pw.director).get(f"{PROJECTS}{pw.deal.id}/"), f"{PROJECTS}{{deal_id}}/", "get", status=200)
    conforms(api(pw.director).get(PROJECTS), PROJECTS, "get", status=200)


@pytest.mark.parametrize(
    ("action", "start", "body"),
    [
        ("send-to-client", S.DRAFT, {}),
        ("client-agreed", S.PENDING_CLIENT, {}),
        ("reject", S.PENDING_CLIENT, {"reason": "Не устраивает"}),
        ("revise", S.REJECTED, {}),
        ("mark-issued", S.PENDING_MANAGER, {"note": "Didox"}),
    ],
)
def test_contract_transitions_follow_the_contract(pw, action, start, body):  # noqa: F811
    contract = contract_in(pw, start)
    template = f"{CONTRACTS}{{id}}/{action}/"
    url = f"{CONTRACTS}{contract.id}/{action}/"
    conforms(api(pw.accountant).post(url, body, format="json"), template, "post", status=200)
    conforms(api(pw.manager).post(url, body, format="json"), template, "post", status=403)
    # второй раз тот же переход уже недопустим
    if action != "reject":
        conforms(api(pw.accountant).post(url, body, format="json"), template, "post", status=409)


def test_contract_refusals_follow_the_contract(pw):  # noqa: F811
    contract = contract_in(pw, S.PENDING_CLIENT)
    conforms(
        api(pw.accountant).post(f"{CONTRACTS}{contract.id}/reject/", {}, format="json"),
        f"{CONTRACTS}{{id}}/reject/",
        "post",
        status=400,
    )
    conforms(
        api(pw.accountant).post(f"{CONTRACTS}999999/client-agreed/", {}, format="json"),
        f"{CONTRACTS}{{id}}/client-agreed/",
        "post",
        status=404,
    )


def test_contract_scan_follows_the_contract(pw):  # noqa: F811
    contract = contract_in(pw, S.ISSUED_EXTERNAL)
    template = f"{CONTRACTS}{{id}}/attach-scan/"
    url = f"{CONTRACTS}{contract.id}/attach-scan/"
    bad = api(pw.accountant).post(url, {"file": scan("x.pdf", b"nope")}, format="multipart")
    conforms(bad, template, "post", status=400)
    conforms(api(pw.manager).post(url, {"file": scan()}, format="multipart"), template, "post", status=403)
    conforms(api(pw.accountant).post(url, {"file": scan()}, format="multipart"), template, "post", status=200)
    conforms(api(pw.accountant).post(url, {"file": scan()}, format="multipart"), template, "post", status=409)


def test_generate_contract_accepts_send_to_client(pw):  # noqa: F811
    response = api(pw.accountant).post(
        f"{CONTRACTS}generate-from-quote/", {"quote_id": pw.quote.id, "send_to_client": False}, format="json"
    )
    conforms(response, f"{CONTRACTS}generate-from-quote/", "post", status=201)


def test_act_scan_and_return_follow_the_contract(pw):  # noqa: F811
    contract = w.add_contract(pw.deal, pw.quote, S.SIGNED)
    invoice = w.add_invoice(pw.deal, InvoiceStatusCode.PAID, total="5", paid="5", contract=contract)
    act = w.add_act(pw.deal, A.ISSUED, contract=contract, invoice=invoice)
    ret = f"{ACTS}{act.id}/record-return/"
    conforms(api(pw.accountant).post(ret, {}, format="json"), f"{ACTS}{{id}}/record-return/", "post", status=400)
    conforms(
        api(pw.manager).post(ret, {"reason": "x"}, format="json"), f"{ACTS}{{id}}/record-return/", "post", status=403
    )
    conforms(
        api(pw.accountant).post(ret, {"reason": "Опечатка"}, format="json"),
        f"{ACTS}{{id}}/record-return/",
        "post",
        status=200,
    )
    conforms(
        api(pw.accountant).post(ret, {"reason": "ещё"}, format="json"),
        f"{ACTS}{{id}}/record-return/",
        "post",
        status=409,
    )

    second = w.add_act(pw.deal, A.ISSUED, contract=contract, invoice=invoice)
    url = f"{ACTS}{second.id}/attach-scan/"
    template = f"{ACTS}{{id}}/attach-scan/"
    conforms(api(pw.accountant).post(url, {}, format="multipart"), template, "post", status=400)
    conforms(api(pw.manager).post(url, {"file": scan()}, format="multipart"), template, "post", status=403)
    conforms(api(pw.accountant).post(url, {"file": scan()}, format="multipart"), template, "post", status=200)
    conforms(api(pw.accountant).post(url, {"file": scan()}, format="multipart"), template, "post", status=409)
    assert PDF

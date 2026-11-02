"""L0-1: отметки доставки клиенту из Платформы — «Отправлено клиенту / В пути» и «Доставлено».

Право — `fulfillment.manage`; переходы — таблица `delivery_progress.TRANSITIONS`; смена статуса — прежний сервис исполнения
(событие шины, накладная), строки поставки получают статус сразу, и клиент принимает доставленное в кабинете.
"""

import datetime

import pytest
from integration.tests import bus_support
from integration.tests import world as w
from parties.models import Contact
from sales.models import ActivityLog, DeliveryLine, DeliveryLineStatus
from sales.services import delivery_lines, delivery_progress

from accounts.models import CompanyMember, CustomUser, WorkspaceRole
from core.tests.openapi_fixtures import conforms
from crm.constants import FulfillmentStatusCode as F
from crm.tests.projects_world import PDF, api, pw, scan  # noqa: F401

pytestmark = pytest.mark.django_db

URL = "/api/v1/crm/projects/{}/delivery/"
TEMPLATE = "/api/v1/crm/projects/{deal_id}/delivery/"


@pytest.fixture
def storekeeper(pw, grant):  # noqa: F811
    """Снабженец с разделом «Склад» полным: право ERP `fulfillment.manage`."""
    owner = WorkspaceRole.objects.get(code="OWNER")
    user = CustomUser.objects.create_user(
        email="store@own.test", username="store@own.test", password="x", is_active=True
    )
    CompanyMember.objects.create(user=user, company=pw.own, role=owner, is_active=True, is_primary=True)
    grant(user, "fulfillment.manage", "supply.manage")
    return user


def _today() -> datetime.date:
    from django.utils import timezone

    return timezone.localdate()


def post(user, deal_id, **fields):
    return api(user).post(URL.format(deal_id), fields, format="multipart")


def status_of(fulfillment) -> str:
    fulfillment.refresh_from_db()
    return fulfillment.status.code


# ── права ─────────────────────────────────────────────────────────────────────────────────────────────


def test_marking_needs_fulfillment_manage(pw, storekeeper):  # noqa: F811
    fulfillment = w.add_fulfillment(pw.deal, F.SHIPPED)
    body = {"action": "in_transit", "on_date": _today().isoformat()}
    for user in (pw.manager, pw.accountant, pw.director):  # без раздела «Склад» полного — права нет
        response = post(user, pw.deal.id, **body)
        assert response.status_code == 403, (user.email, response.content)
        assert response.json()["detail"] == "ROLE_NOT_PERMITTED"
    assert post(pw.outsider, pw.deal.id, **body).status_code == 403
    assert status_of(fulfillment) == F.SHIPPED
    assert post(storekeeper, pw.deal.id, **body).status_code == 200
    assert status_of(fulfillment) == F.IN_TRANSIT


def test_admin_marks_too(pw):  # noqa: F811
    w.add_fulfillment(pw.deal, F.SHIPPED)
    assert post(pw.admin, pw.deal.id, action="delivered", on_date=_today().isoformat()).status_code == 200


def test_card_offers_actions_only_to_who_may_mark(pw, storekeeper):  # noqa: F811
    w.add_fulfillment(pw.deal, F.SHIPPED)
    card = api(storekeeper).get(f"/api/v1/crm/projects/{pw.deal.id}/").json()
    assert card["fulfillment"]["actions"] == ["in_transit", "delivered"]
    assert card["fulfillment"]["proof_name"] is None and card["fulfillment"]["proof_attachment_id"] is None
    assert api(pw.manager).get(f"/api/v1/crm/projects/{pw.deal.id}/").json()["fulfillment"]["actions"] == []


@pytest.mark.parametrize(
    ("status", "actions"),
    [
        (F.PENDING, ["in_transit", "delivered"]),
        (F.SHIPPED, ["in_transit", "delivered"]),
        (F.IN_TRANSIT, ["delivered"]),
        (F.DELIVERED, []),
        (F.ACCEPTED, []),
        (F.DISPUTED, []),
    ],
)
def test_available_actions_follow_the_status(pw, storekeeper, status, actions):  # noqa: F811
    fulfillment = w.add_fulfillment(pw.deal, status)
    assert delivery_progress.available_actions(fulfillment, storekeeper) == actions


# ── переходы ──────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("start", "action", "expected"),
    [
        (F.PENDING, "in_transit", F.IN_TRANSIT),
        (F.SHIPPED, "in_transit", F.IN_TRANSIT),
        (F.PENDING, "delivered", F.DELIVERED),
        (F.SHIPPED, "delivered", F.DELIVERED),
        (F.IN_TRANSIT, "delivered", F.DELIVERED),
    ],
)
def test_allowed_transitions(pw, storekeeper, start, action, expected):  # noqa: F811
    fulfillment = w.add_fulfillment(pw.deal, start)
    response = post(storekeeper, pw.deal.id, action=action, on_date=_today().isoformat())
    assert response.status_code == 200, response.content
    assert status_of(fulfillment) == expected
    assert fulfillment.shipped_at is not None, "в пути и доставлено — товар ушёл"


@pytest.mark.parametrize(
    ("start", "action"),
    [
        (F.IN_TRANSIT, "in_transit"),
        (F.DELIVERED, "in_transit"),
        (F.DELIVERED, "delivered"),
        (F.ACCEPTED, "in_transit"),
        (F.ACCEPTED, "delivered"),
        (F.DISPUTED, "delivered"),
    ],
)
def test_refused_transitions_change_nothing(pw, storekeeper, start, action):  # noqa: F811
    fulfillment = w.add_fulfillment(pw.deal, start)
    response = post(storekeeper, pw.deal.id, action=action, on_date=_today().isoformat(), file=scan())
    assert response.status_code == 409
    assert response.json()["detail"] == "DELIVERY_TRANSITION_NOT_ALLOWED"
    assert status_of(fulfillment) == start
    assert fulfillment.delivery_proof_id is None
    assert not ActivityLog.objects.filter(event_code__startswith="project.delivery_").exists()


def test_no_fulfillment_yet_is_a_conflict(pw, storekeeper):  # noqa: F811
    response = post(storekeeper, pw.deal.id, action="in_transit", on_date=_today().isoformat())
    assert response.status_code == 409 and response.json()["detail"] == "FULFILLMENT_NOT_READY"
    assert post(storekeeper, 999999, action="in_transit", on_date=_today().isoformat()).status_code == 404


# ── поля ──────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"action": "lost", "on_date": "2026-01-01"}, "DELIVERY_ACTION_INVALID"),
        ({"action": "delivered", "on_date": ""}, "DELIVERY_DATE_INVALID"),
        ({"action": "delivered", "on_date": "31.12.2026"}, "DELIVERY_DATE_INVALID"),
        ({"action": "delivered", "waybill": "x" * 129}, "WAYBILL_TOO_LONG"),
        ({"action": "delivered", "file": "bad"}, "PROOF_INVALID"),
    ],
)
def test_field_errors(pw, storekeeper, fields, code):  # noqa: F811
    fulfillment = w.add_fulfillment(pw.deal, F.SHIPPED)
    body = {"on_date": _today().isoformat(), **fields}
    if body.get("file") == "bad":
        body["file"] = scan("proof.exe", b"MZ\x90\x00", "application/octet-stream")
    response = post(storekeeper, pw.deal.id, **body)
    assert response.status_code == 400, response.content
    assert response.json()["detail"] == code
    assert status_of(fulfillment) == F.SHIPPED


def test_future_date_is_refused(pw, storekeeper):  # noqa: F811
    w.add_fulfillment(pw.deal, F.SHIPPED)
    tomorrow = (_today() + datetime.timedelta(days=1)).isoformat()
    response = post(storekeeper, pw.deal.id, action="delivered", on_date=tomorrow)
    assert response.status_code == 400 and response.json()["detail"] == "DELIVERY_DATE_IN_FUTURE"


def test_delivery_cannot_precede_shipping(pw, storekeeper):  # noqa: F811
    from django.utils import timezone

    w.add_fulfillment(pw.deal, F.IN_TRANSIT, shipped_at=timezone.now())
    yesterday = (_today() - datetime.timedelta(days=1)).isoformat()
    response = post(storekeeper, pw.deal.id, action="delivered", on_date=yesterday)
    assert response.status_code == 400 and response.json()["detail"] == "DELIVERY_DATE_BEFORE_SHIPPED"


def test_delivered_with_date_waybill_and_proof(pw, storekeeper):  # noqa: F811
    from django.utils import timezone

    fulfillment = w.add_fulfillment(pw.deal, F.SHIPPED)
    day = _today() - datetime.timedelta(days=2)
    response = post(
        storekeeper, pw.deal.id, action="delivered", on_date=day.isoformat(), waybill=" CMR-0042 ", file=scan()
    )
    assert response.status_code == 200, response.content
    card = response.json()
    assert card["fulfillment"]["status"] == F.DELIVERED and card["fulfillment"]["actions"] == []
    assert card["fulfillment"]["tracking_number"] == "CMR-0042"
    assert card["fulfillment"]["proof_name"] == "scan.pdf" and card["fulfillment"]["proof_attachment_id"]
    fulfillment.refresh_from_db()
    assert timezone.localtime(fulfillment.delivered_at).date() == day
    assert fulfillment.delivery_proof.deal_id == pw.deal.id
    log = ActivityLog.objects.get(event_code="project.delivery_delivered")
    assert log.user == storekeeper and log.event_params["waybill"] == "CMR-0042"
    assert log.event_params["proof_name"] == "scan.pdf" and log.event_params["on_date"] == day.isoformat()
    assert [row["code"] for row in card["journal"]][:1] == ["project.delivery_delivered"]


def test_in_transit_publishes_the_status_on_the_bus(pw, storekeeper):  # noqa: F811
    w.add_fulfillment(pw.deal, F.SHIPPED)
    assert post(storekeeper, pw.deal.id, action="in_transit", on_date=_today().isoformat()).status_code == 200
    event = bus_support.only("delivery.status_changed")
    bus_support.assert_matches_contract(event)
    assert event["data"]["payload"]["status"] == "in_transit"


def test_responses_follow_the_contract(pw, storekeeper):  # noqa: F811
    w.add_fulfillment(pw.deal, F.SHIPPED)
    url = URL.format(pw.deal.id)
    today = _today().isoformat()
    conforms(
        api(storekeeper).post(url, {"action": "in_transit", "on_date": today}, format="multipart"),
        TEMPLATE,
        "post",
        status=200,
    )
    conforms(
        api(storekeeper).post(url, {"action": "in_transit", "on_date": today}, format="multipart"),
        TEMPLATE,
        "post",
        status=409,
    )
    conforms(api(storekeeper).post(url, {"action": "x"}, format="multipart"), TEMPLATE, "post", status=400)
    conforms(api(pw.manager).post(url, {"action": "delivered"}, format="multipart"), TEMPLATE, "post", status=403)
    conforms(
        api(storekeeper).post(URL.format(999999), {"action": "delivered"}, format="multipart"),
        TEMPLATE,
        "post",
        status=404,
    )


# ── сквозной путь: отгрузка → в пути → доставлено → клиент принимает ─────────────────────────────────────


def test_shipped_then_in_transit_then_delivered_then_client_accepts(storekeeper, pw):  # noqa: F811
    deal = w.make_deal(pw.client, "CONTRACT_SIGNED", title="Поставка двигателя")
    w.add_order_quote(deal)
    fulfillment = w.add_fulfillment(deal, F.SHIPPED)
    contact = Contact.objects.create(company=pw.client, name="Клиент Тестовый", email="buyer@client.test", can_act=True)
    delivery_lines.sync_delivery_lines([fulfillment])
    lines = list(DeliveryLine.objects.filter(deal=deal))
    assert lines and {line.status for line in lines} == {DeliveryLineStatus.SHIPPED}
    assert delivery_lines.accept_delivery_line(lines[0].pk, contact) == (None, "DELIVERY_LINE_NOT_ACCEPTABLE")

    assert post(storekeeper, deal.id, action="in_transit", on_date=_today().isoformat()).status_code == 200
    assert set(DeliveryLine.objects.filter(deal=deal).values_list("status", flat=True)) == {
        DeliveryLineStatus.IN_TRANSIT
    }
    assert post(storekeeper, deal.id, action="delivered", on_date=_today().isoformat()).status_code == 200
    assert set(DeliveryLine.objects.filter(deal=deal).values_list("status", flat=True)) == {
        DeliveryLineStatus.DELIVERED
    }

    for line in lines:
        accepted, error = delivery_lines.accept_delivery_line(line.pk, contact)
        assert error is None and accepted.status == DeliveryLineStatus.ACCEPTED
    assert status_of(fulfillment) == F.ACCEPTED
